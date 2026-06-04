// Synthetic major-project Neo4j import
// Synthetic-only demonstration graph; contains no production records.
// Copy neo4j_nodes_small.csv and neo4j_edges_small.csv into Neo4j's import directory before running.

CREATE CONSTRAINT synthetic_major_project_node_id IF NOT EXISTS
FOR (n:SyntheticMajorProjectNode)
REQUIRE n.node_id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///neo4j_nodes_small.csv' AS row
CREATE (n:SyntheticMajorProjectNode)
SET n.node_id = row.node_id,
    n.label = row.label,
    n.biz_id = row.biz_id,
    n.name = row.name,
    n.properties_json = row.properties,
    n.synthetic_notice = 'Synthetic major-project demo only; no production records';

LOAD CSV WITH HEADERS FROM 'file:///neo4j_edges_small.csv' AS row
MATCH (source:SyntheticMajorProjectNode {node_id: row.source_node_id})
MATCH (target:SyntheticMajorProjectNode {node_id: row.target_node_id})
CREATE (source)-[r:SYNTHETIC_KG_EDGE]->(target)
SET r.edge_id = row.edge_id,
    r.edge_type = row.edge_type,
    r.confidence = toFloat(row.confidence),
    r.match_method = row.match_method,
    r.evidence_json = row.evidence,
    r.synthetic_notice = 'Synthetic major-project demo only; no production records';
