import pytest

from eacore.embedded import StereoFormatError, duid, is_guid, link_ends, parse_kv, parse_stereotypes


def test_is_guid_accepts_ea_mixed_case():
    # EA writes the 3rd/4th groups in lowercase: this is normal, not malformed.
    assert is_guid("{04468E7C-0837-4f18-926C-CDE648A3912B}")
    assert not is_guid("04468E7C-0837-4f18-926C-CDE648A3912B")
    assert not is_guid("{nope}")
    assert not is_guid(None)


def test_duid_and_link_ends():
    assert duid("DUID=9E247B5B;HideIcon=0;AttCustom=0;") == "9E247B5B"
    assert duid("HideIcon=0;") is None
    assert duid(None) is None
    assert link_ends("Mode=3;EOID=D04C7478;SOID=9E247B5B;Color=-1;LWidth=0;") == ("9E247B5B", "D04C7478")
    assert link_ends(None) == (None, None)


def test_parse_kv_keeps_first_value_and_ignores_fragments():
    assert parse_kv("SX=2;SY=91;$LLB=;LLT=;junk;") == {"SX": "2", "SY": "91", "$LLB": "", "LLT": ""}


def test_parse_stereotypes_fqname_and_guid_variants():
    text = "@STEREO;Name=DataElement;FQName=NAFv4-Core::DataElement;@ENDSTEREO;@STEREO;Name=idlStruct;@ENDSTEREO;"
    parsed = parse_stereotypes(text)
    assert [(s.name, s.fqname) for s in parsed] == [("DataElement", "NAFv4-Core::DataElement"), ("idlStruct", None)]
    guid = parse_stereotypes("@STEREO;Name=hibw;GUID={5570252E-D8E7-4bd3-818A-6D9E49E71F93};@ENDSTEREO;")
    assert guid[0].guid == "{5570252E-D8E7-4bd3-818A-6D9E49E71F93}"
    assert parse_stereotypes("") == []


@pytest.mark.parametrize("bad", ["@STEREO;Name=X;", "Name=X;@ENDSTEREO;", "@STEREO;FQName=P::X;@ENDSTEREO;"])
def test_parse_stereotypes_rejects_malformed(bad):
    with pytest.raises(StereoFormatError):
        parse_stereotypes(bad)
