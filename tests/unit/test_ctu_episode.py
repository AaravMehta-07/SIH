from pathlib import Path

from foresight.data.ctu import build_ctu_episode
from foresight.ingest.ctu_adapter import parse_ctu_binetflow

HEADER = "StartTime,Dur,Proto,SrcAddr,Sport,Dir,DstAddr,Dport,State,sTos,dTos,TotPkts,TotBytes,SrcBytes,Label\n"


def test_ctu_episode_uses_address_scope_and_only_c2_task(tmp_path: Path):
    path = tmp_path / "capture.binetflow"
    path.write_text(
        HEADER
        + "2011/08/16 10:01:58.000001,1.5,tcp,147.32.84.165,1234,  <->,8.8.8.8,6667,CON,0,0,5,500,300,flow=From-Botnet-V47-TCP-IRC-CC1\n"
        + "2011/08/16 10:40:00.000001,1.0,tcp,147.32.84.170,1235,  <->,1.1.1.1,443,CON,0,0,8,800,500,flow=From-Normal-V47\n"
        + "2011/08/16 11:00:00.000001,1.0,udp,147.32.84.170,1235,  <->,1.1.1.1,53,CON,0,0,2,200,100,flow=From-Normal-V47\n",
        encoding="utf-8",
    )
    parsed = parse_ctu_binetflow(path, scenario_id="06")
    episode = build_ctu_episode(parsed, partition=1)
    assert episode.capture.synthetic is False
    assert episode.qualified_tasks == (0, 3)
    assert "addr:147.32.84.165" in episode.internal_entity_ids()
    assert {g.task_index for g in episode.ground_truth} == {0, 3}
    assert episode.capture.capability_report.state_of("packet_timing") == "not_available"
