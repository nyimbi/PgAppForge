"""
Apache AGE graph database support for pgappforge.

Apache AGE (A Graph Extension) is a PostgreSQL extension that adds
graph database functionality using OpenCypher query language.

Prerequisites::

    # Install Apache AGE PostgreSQL extension
    CREATE EXTENSION age;
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;

Usage::

    from pgappforge.database.age import AGEManager, AGEGraph

    # Connect to an AGE-enabled database
    mgr = AGEManager(engine)

    # Create a graph
    graph = mgr.create_graph('social_network')

    # Execute OpenCypher
    rows = graph.cypher(
        'CREATE (a:Person {name: $name}) RETURN a',
        params={'name': 'Alice'}
    )

    # Query
    friends = graph.cypher(
        'MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name'
    )
"""
from .manager import AGEManager
from .graph import AGEGraph
from .types import Vertex, Edge, Path

__all__ = ['AGEManager', 'AGEGraph', 'Vertex', 'Edge', 'Path']
