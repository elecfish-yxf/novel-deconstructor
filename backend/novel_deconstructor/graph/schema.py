from dataclasses import dataclass


@dataclass
class GraphEntity:
    id: str
    name: str
    type: str
    description: str = ""


@dataclass
class GraphRelationship:
    source: str
    target: str
    type: str
    evidence: str = ""
