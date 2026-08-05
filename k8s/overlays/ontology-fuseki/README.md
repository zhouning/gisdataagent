# Ontology Fuseki overlay

This overlay adds the rebuildable Apache Jena Fuseki/TDB2 read projection to
the base GIS Data Agent deployment. PostgreSQL `gda_ontology` remains the
authority. The SHA-512-verified Apache Jena/Fuseki 5.5.0 image bootstraps the
immutable `2.0.1` RDF package into TDB2 and exposes only query and read-only
Graph Store endpoints. The versioned projection Job verifies that all 528,252
triples are queryable before release acceptance.

Build and publish the ontology image to the deployment registry, then override
the image name in the environment overlay when necessary:

```bash
docker build -f docker/ontology-fuseki/Dockerfile \
  -t registry.example.com/gisdataagent-ontology-fuseki:5.5.0-nr-2.0.1 .
docker push registry.example.com/gisdataagent-ontology-fuseki:5.5.0-nr-2.0.1
cd k8s/overlays/ontology-fuseki
kustomize edit set image \
  gisdataagent-ontology-fuseki=registry.example.com/gisdataagent-ontology-fuseki:5.5.0-nr-2.0.1
kubectl apply -k .
```

The Fuseki Service is cluster-internal and NetworkPolicy-limited to the app and
projection verifier. Updating a package requires a new immutable ontology image
tag, a versioned verifier Job name/count contract, and a normal StatefulSet
rollout. No Fuseki administrator credential is injected into the runtime app.
