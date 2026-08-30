# AgentOps Discovery Sandbox: Docker Desktop overlay

Use this overlay only for the local Docker Desktop kind cluster. The generic
`temporal-agentops-discovery-sandbox` overlay remains the portable deployment
contract and pins the registry image digest
`sha256:20a7c649473a81c874b5d9197aa92af62da2882d36407c2f17c3dc6f71e74a77`.

`kind load docker-image` imports the same verified image as a local tag and
rewrites its platform manifest reference inside containerd. This overlay uses
that explicit tag with `imagePullPolicy: Never`; verify the node image ID before
applying it. Do not promote this overlay to staging or production.
