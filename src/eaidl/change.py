from eaidl.config import Configuration
from sqlalchemy.ext.automap import automap_base
import sqlalchemy
import logging
from typing import Optional, List, Dict


log = logging.getLogger(__name__)

#: We use automap and reflection for tables now. We could switch to declarative,
#: but most of the fields are useless anyway, and because we don't have good
#: documentation every use of field need to be investigated inside example
#: database.
#:
#: https://docs.sqlalchemy.org/en/20/orm/extensions/automap.html#generating-mappings-from-an-existing-metadata
#:
base = automap_base()


@sqlalchemy.event.listens_for(base.metadata, "column_reflect")
def column_reflect(inspector, table, column_info):
    """
    We do conversion of column names to lowe case, so we can support different types of databased.
    In sqlite we have Object_ID and UpperBound, in postresql we have object_id and upperbound.

    https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html#mapper-automated-reflection-schemes

    """
    column_info["key"] = "attr_%s" % column_info["name"].lower()


class ModelChanger:
    """Utility for making bulk changes to EA model database."""

    def __init__(self, config: Configuration) -> None:
        self.config = config
        # Import here to avoid circular dependency
        from eaidl.load import ModelParser, base as parser_base

        self.parser = ModelParser(config)
        self.session = self.parser.session
        # Use the base from parser (already prepared)
        self.TObject = parser_base.classes.t_object
        self.TAttribute = parser_base.classes.t_attribute

    def is_enum(self, obj) -> bool:
        """Check if an object is an enum based on stereotypes."""
        stereotypes = self.parser.get_stereotypes(obj.attr_ea_guid)
        return self.config.stereotypes.idl_enum in stereotypes

    def check_enum_prefixes(self, enum_name: Optional[str] = None) -> Dict[str, List[Dict[str, str]]]:
        """
        Check enum attribute prefixes for correctness.

        Args:
            enum_name: Optional specific enum name to check. If None, checks all enums.

        Returns:
            Dict mapping enum names to lists of issues found.
            Each issue is a dict with 'attribute', 'current', 'expected' keys.
        """
        issues = {}

        # Query all objects
        query = self.session.query(self.TObject)
        if enum_name:
            query = query.filter(self.TObject.attr_name == enum_name)

        objects = query.all()

        for obj in objects:
            if not self.is_enum(obj):
                continue

            # Get all attributes for this enum
            attributes = (
                self.session.query(self.TAttribute)
                .filter(self.TAttribute.attr_object_id == obj.attr_object_id)
                .order_by(self.TAttribute.attr_pos)
                .all()
            )

            enum_issues = []
            for attr in attributes:
                if attr.attr_name and not attr.attr_name.startswith(obj.attr_name + "_"):
                    # Check if it has any prefix at all
                    if "_" in attr.attr_name:
                        current_prefix = attr.attr_name.split("_", 1)[0]
                        expected_name = obj.attr_name + "_" + attr.attr_name.split("_", 1)[1]
                    else:
                        current_prefix = "(none)"
                        expected_name = obj.attr_name + "_" + attr.attr_name

                    enum_issues.append(
                        {
                            "attribute_id": attr.attr_id,
                            "attribute": attr.attr_name,
                            "current": attr.attr_name,
                            "expected": expected_name,
                            "current_prefix": current_prefix,
                            "expected_prefix": obj.attr_name,
                        }
                    )

            if enum_issues:
                issues[obj.attr_name] = enum_issues

        return issues

    def fix_enum_prefixes(self, enum_name: Optional[str] = None, dry_run: bool = True) -> Dict[str, int]:
        """
        Fix enum attribute prefixes to match enum name.

        Args:
            enum_name: Optional specific enum name to fix. If None, fixes all enums.
            dry_run: If True, only show what would be changed without committing.

        Returns:
            Dict with statistics: {'checked': N, 'fixed': M, 'enums_affected': K}
        """
        issues = self.check_enum_prefixes(enum_name)
        stats = {"checked": 0, "fixed": 0, "enums_affected": len(issues)}

        for enum, enum_issues in issues.items():
            log.info(f"Enum: {enum} (has {len(enum_issues)} issues)")
            for issue in enum_issues:
                stats["checked"] += 1
                log.info(f"  {issue['current']} -> {issue['expected']}")

                if not dry_run:
                    # Update the attribute name in the database
                    attr = (
                        self.session.query(self.TAttribute)
                        .filter(self.TAttribute.attr_id == issue["attribute_id"])
                        .first()
                    )
                    if attr:
                        attr.attr_name = issue["expected"]
                        stats["fixed"] += 1

        if not dry_run and stats["fixed"] > 0:
            self.session.commit()
            log.info(f"✓ Committed {stats['fixed']} changes to database")
        elif not dry_run:
            log.info("No changes needed")
        else:
            log.info(f"Dry run: would fix {stats['checked']} attributes in {stats['enums_affected']} enums")

        return stats

    def change(self) -> None:
        """Placeholder for custom bulk changes."""
        pass
        # TConnector = base.classes.t_connector
        # t_connectors = self.session.query(TConnector).filter(TConnector.attr_connector_type == "Association").all()
        # for connector in t_connectors:
        #     if connector.attr_destrole is not None:
        #         if connector.attr_destrole.startswith("a_"):
        #             print(f"{connector.attr_destrole} -> {connector.attr_destrole[2:]}")
        #             connector.attr_destrole = connector.attr_destrole[2:]

        # # Commit the changes to the database
        # self.session.commit()
        # TAttribute = base.classes.t_attribute
        # t_attributes = self.session.query(TAttribute).all()

        # for attribute in t_attributes:
        #     if attribute.attr_name is not None:
        #         if attribute.attr_name.startswith("a_"):
        #             print(f"{attribute.attr_name} -> {attribute.attr_name[2:]}")
        #             attribute.attr_name = attribute.attr_name[2:]
        # # Commit the changes to the database
        # self.session.commit()
