from pathlib import Path
import json


def export_graph(output_dir: Path, graph: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "entities.json").write_text(
        json.dumps(graph.get("entities", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "relationships.json").write_text(
        json.dumps(graph.get("relationships", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "graph_summary.md").write_text(graph.get("summary", ""), encoding="utf-8")
