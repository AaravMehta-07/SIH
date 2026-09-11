from pathlib import Path

from foresight.ingest.ctu_adapter import classify_ctu_label, parse_ctu_binetflow


HEADER = "StartTime,Dur,Proto,SrcAddr,Sport,Dir,DstAddr,Dport,State,sTos,dTos,TotPkts,TotBytes,SrcBytes,Label\n"


def test_ctu_adapter_keeps_background_separate_and_masks_packet_fields(tmp_path: Path):
    path = tmp_path / "capture.binetflow"
    path.write_text(
        HEADER
        + "2011/08/16 10:01:58.000001,1.5,tcp,147.32.84.165,1234,  <->,8.8.8.8,80,CON,0,0,5,500,300,flow=Background-TCP-Established\n"
        + "2011/08/16 10:02:00.000001,2.0,tcp,147.32.84.170,1235,  <->,1.1.1.1,443,CON,0,0,8,800,500,flow=From-Normal-V47\n",
        encoding="utf-8",
    )
    parsed = parse_ctu_binetflow(path, scenario_id="06", materialize_events=True)
    assert parsed.stream.quality.accepted_records == 2
    assert [label.category for label in parsed.labels] == ["normal"]
    assert parsed.stream.notes["label_counts"] == {
        "normal": 1, "botnet": 0, "background": 1, "unresolved": 0
    }
    assert parsed.stream.capability.state_of("packet_timing") == "not_available"
    assert parsed.stream.capability.state_of("flow_total_bytes") == "observed"
    assert parsed.stream.notes["background_is_benign"] is False
    assert parsed.stream.events[0].subjects[0].entity_type == "address"
    assert parsed.stream.events[0].eligible_at(parsed.stream.events[0].available_at_ns)


def test_ctu_label_mapping_is_conservative():
    assert classify_ctu_label("flow=From-Normal-V42")[0] == "normal"
    assert classify_ctu_label("flow=To-Normal-V42")[0] == "unresolved"
    assert classify_ctu_label("flow=To-Botnet-V42")[1] == ()
    assert classify_ctu_label("flow=From-Botnet-V42-TCP-HTTP")[1] == (0,)
    assert classify_ctu_label("flow=From-Botnet-V42-TCP-IRC-CC1")[1] == (0, 3)


def test_ctu_adapter_rejects_duplicate_or_guessed_schema(tmp_path: Path):
    path = tmp_path / "bad.binetflow"
    path.write_text("StartTime,StartTime\n1,2\n", encoding="utf-8")
    try:
        parse_ctu_binetflow(path, scenario_id="06")
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate headers must be rejected")
