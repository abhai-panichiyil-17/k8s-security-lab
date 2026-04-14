Kubernetes Security Lab — Zero Trust Microsegmentation with Calico
Author: Abhai Panichiyil
Based on: MSc Research — Implementing Zero Trust Security in Multi-Cloud and Hybrid Cloud Environments
Stack: Minikube · Calico CNI · Kubernetes · Docker · Ubuntu 24.04

Table of Contents

Project Overview
Zero Trust Principles Applied
Architecture
Prerequisites
Environment Setup
Deployment
Network Policies Explained
Testing and Verification
Results Summary
MITRE ATT&CK Mapping
Repository Structure
Key Concepts Reference


Project Overview
This lab demonstrates Zero Trust microsegmentation in a Kubernetes cluster using Calico as the Container Network Interface (CNI). A three-tier application (Nginx → Flask → Postgres) is deployed across three isolated namespaces, with Calico NetworkPolicies enforcing strict traffic control between tiers.
The goal is to prove that even inside a Kubernetes cluster, lateral movement is prevented — a compromised frontend pod cannot directly reach the database, and no pod can communicate with anything it hasn't been explicitly permitted to reach.
This directly implements the findings from my MSc practicum paper on Zero Trust Architecture in hybrid cloud environments.

Zero Trust Principles Applied
Zero Trust is a security model that assumes no user, device, or network segment is inherently trustworthy — even those already inside the perimeter.
PrincipleHow It Is Implemented in This LabNever trust, always verifyEvery pod-to-pod connection is evaluated against Calico NetworkPolicies before being allowedLeast privilegeEach pod can only communicate with exactly what it needs — nothing moreAssume breachEven if the frontend is compromised, Calico prevents it from reaching the database directly

Architecture
Internet
    |
[NodePort :30080]
    |
[Nginx Pod]          ← frontend namespace
    |
    | ALLOWED by Calico (port 5000)
    ↓
[Flask API Pod]      ← backend namespace
    |
    | ALLOWED by Calico (port 5432)
    ↓
[Postgres Pod]       ← database namespace

Frontend → Database: BLOCKED by Calico (no direct path exists)
Backend → Frontend:  BLOCKED by Calico (no reverse path)
Why Three Namespaces?
Kubernetes namespaces act as logical boundaries inside the cluster. By placing each tier in its own namespace, we can write Calico NetworkPolicies that say "only the backend namespace may talk to the database namespace." This is namespace-level microsegmentation — a core pattern in Zero Trust network design.
Without separate namespaces, enforcing this kind of granular isolation would require much more complex pod-label-only selectors and would be harder to audit and maintain.

Prerequisites
ToolVersion UsedPurposeVirtualBox7.1.0Hypervisor for local Ubuntu VMUbuntu24.04 LTSHost OS for the lab environmentDocker29.3.0Container runtime — Minikube driverkubectlv1.35.3Kubernetes CLI — interact with the clusterMinikubeLatestSingle-node local Kubernetes cluster
VM Specs: 6GB RAM · 4 CPUs · SSD storage · VMSVGA graphics

Environment Setup
1. Start Docker
Docker must be running before Minikube can start, as it uses Docker as its node driver.
bashsudo systemctl start docker
sudo systemctl status docker   # Confirm: Active (running)
2. Start Minikube with Calico
bashminikube start --driver=docker --cni=calico --cpus=2 --memory=3000
Flag explanations:

--driver=docker — uses Docker (already installed) as the engine, avoiding a VM-inside-a-VM
--cni=calico — installs Calico as the network plugin; without this, NetworkPolicies are silently ignored
--cpus=2 --memory=3000 — allocates half the VM's resources to the cluster, leaving headroom for the OS

3. Verify Cluster Health
bashkubectl get nodes
# Expected: minikube   Ready   control-plane

kubectl get pods -n kube-system | grep calico
# Expected: calico-kube-controllers   1/1   Running
#           calico-node               1/1   Running

Note: On this version of Minikube, Calico pods land in kube-system rather than calico-system. Both calico-kube-controllers and calico-node must show Running before proceeding.

4. Create Namespaces
bashkubectl create namespace frontend
kubectl create namespace backend
kubectl create namespace database
Each namespace maps to one tier of the application. Calico NetworkPolicies reference these namespaces by their kubernetes.io/metadata.name label.

Deployment
Frontend — Nginx
File: k8s/deployments/nginx.yaml
Nginx acts as the public-facing web server. It is the only pod exposed to the outside world via a NodePort service on port 30080.
bashkubectl apply -f k8s/deployments/nginx.yaml
Key points:

Labels app: nginx and tier: frontend are used by Calico to identify this pod
NodePort service exposes it at localhost:30080
All other pods use ClusterIP (internal only)

Backend — Flask API
File: k8s/deployments/flask.yaml
A mock Flask API implemented using Python's built-in HTTP server. In a production scenario this would be a real application server. For this lab, its role is to represent the middle tier that brokers requests between the frontend and database.
bashkubectl apply -f k8s/deployments/flask.yaml
Key points:

ClusterIP service — not reachable from outside the cluster
Only Nginx is permitted to send traffic to this pod (enforced by Calico)

Database — Postgres
File: k8s/deployments/postgres.yaml
Postgres is the most sensitive tier. It holds data and should never be directly reachable from the frontend or from outside the cluster.
bashkubectl apply -f k8s/deployments/postgres.yaml
Key points:

ClusterIP service — internal only
Only Flask is permitted to send traffic to this pod (enforced by Calico)
Egress is completely denied — Postgres cannot initiate any outbound connections

Verify All Pods Running
bashkubectl get pods --all-namespaces
Expected output:
NAMESPACE   NAME           READY   STATUS    RESTARTS   AGE
frontend    nginx-pod      1/1     Running   0          Xm
backend     flask-pod      1/1     Running   0          Xm
database    postgres-pod   1/1     Running   0          Xm

Network Policies Explained
Calico's key behaviour: once any NetworkPolicy is applied to a pod, all traffic to and from that pod is denied by default. You only write ALLOW rules — everything else is automatically blocked. This is deny-by-default, the foundation of Zero Trust networking.
Frontend Policy
File: k8s/network-policies/frontend-policy.yaml
yamlingress:
  - {}                          # Allow ALL inbound (public-facing pod)
egress:
  - to backend namespace        # Only allowed to talk to Flask
    port 5000
  - to kube-system namespace    # DNS queries to CoreDNS
    port 53 (UDP + TCP)
The DNS egress rule is critical — without it, Calico blocks DNS queries to CoreDNS (which lives in kube-system), and service name resolution fails entirely. This is a common gotcha when first implementing NetworkPolicies.
Backend Policy
File: k8s/network-policies/backend-policy.yaml
yamlingress:
  - from frontend namespace     # Only Nginx can reach Flask
    port 5000
egress:
  - to database namespace       # Only allowed to talk to Postgres
    port 5432
  - to kube-system namespace    # DNS queries to CoreDNS
    port 53 (UDP + TCP)
Flask sits strictly in the middle. It cannot be reached by anything except Nginx, and it cannot reach anything except Postgres. This is least privilege at the network level.
Database Policy
File: k8s/network-policies/database-policy.yaml
yamlingress:
  - from backend namespace      # Only Flask can reach Postgres
    port 5432
egress: []                      # No outbound traffic whatsoever
The empty egress array ([]) is deliberate and important. A database has no legitimate reason to initiate connections to anything. Denying all egress means that even if an attacker gains a foothold inside the Postgres pod, they cannot reach other services, exfiltrate data over the network, or pivot to other parts of the cluster.

Testing and Verification
All tests run using kubectl exec to jump inside pods and attempt connections.

Why connections time out instead of being refused: Calico silently drops blocked packets — it does not send back a TCP RST or ICMP rejection. The connecting pod just waits until its timeout expires. This is deliberate behaviour — it avoids revealing firewall rules to potential attackers.

Test 1 — Frontend → Backend (Should SUCCEED)
bashkubectl exec -it nginx-pod -n frontend -- curl flask-service.backend.svc.cluster.local:5000
Expected: HTML response from Flask mock server
Why it works: frontend-policy explicitly allows egress to backend on port 5000
Test 2 — Frontend → Database (Should be BLOCKED)
bashkubectl exec -it nginx-pod -n frontend -- curl <postgres-clusterip>:5432 --max-time 10
Expected: curl: (28) Connection timed out
Why it's blocked: frontend-policy has no egress rule for the database namespace; Calico drops the packets
Test 3 — Backend → Database (Should SUCCEED)
bashkubectl exec -it flask-pod -n backend -- python3 -c "
import socket
s = socket.socket()
s.settimeout(5)
s.connect(('postgres-service.database.svc.cluster.local', 5432))
print('CONNECTION SUCCESS')
s.close()
"
Expected: CONNECTION SUCCESS
Why it works: backend-policy allows egress to database on port 5432; database-policy allows ingress from backend on port 5432

Note: curl is not available in the Python slim image, so we use Python's socket library directly to test TCP connectivity.

Test 4 — Backend → Frontend (Should be BLOCKED)
bashkubectl exec -it flask-pod -n backend -- python3 -c "
import socket
s = socket.socket()
s.settimeout(5)
s.connect(('<nginx-clusterip>', 80))
print('CONNECTION SUCCESS')
s.close()
"
Expected: socket.timeout: timed out
Why it's blocked: backend-policy only allows egress to the database namespace — there is no rule permitting Flask to talk back to Nginx

Results Summary
SourceDestinationPortResultPolicy ResponsibleFrontend (Nginx)Backend (Flask)5000✅ ALLOWEDfrontend-policy egressFrontend (Nginx)Database (Postgres)5432❌ BLOCKEDNo matching ruleBackend (Flask)Database (Postgres)5432✅ ALLOWEDbackend-policy egress + database-policy ingressBackend (Flask)Frontend (Nginx)80❌ BLOCKEDNo matching rule
All four results match the intended Zero Trust design. Traffic flows strictly down the chain (Frontend → Backend → Database) with no lateral movement permitted.

MITRE ATT&CK Mapping
TechniqueIDLab RelevanceLateral Movement: Remote ServicesT1021Calico blocks pod-to-pod lateral movement across namespacesDiscovery: Network Service ScanningT1046Blocked connections produce timeouts, not rejections — harder to enumerateExfiltration over networkT1041Database egress deny-all prevents data exfiltration from Postgres
The Kali attack simulation phase (planned) will probe the cluster from an external VM and document which attack vectors Calico blocks, mapped to these techniques.

Repository Structure
k8s-security-lab/
├── README.md
├── diagrams/
│   └── architecture.png
├── k8s/
│   ├── namespaces.yaml
│   ├── deployments/
│   │   ├── nginx.yaml
│   │   ├── flask.yaml
│   │   └── postgres.yaml
│   ├── services/
│   │   ├── nginx-service.yaml
│   │   ├── flask-service.yaml
│   │   └── postgres-service.yaml
│   └── network-policies/
│       ├── frontend-policy.yaml
│       ├── backend-policy.yaml
│       └── database-policy.yaml
└── app/
    ├── Dockerfile
    └── app.py

Key Concepts Reference
Pod vs Deployment

Pod — the smallest deployable unit in Kubernetes. Contains one or more containers that share a network namespace and storage. Has a single IP address inside the cluster.
Deployment — a controller that manages pods. Handles automatic restarts if a pod crashes, scaling, and rolling updates. For production use, you always use Deployments rather than bare Pods. This lab uses bare Pods for simplicity.

ClusterIP vs NodePort

ClusterIP — the default service type. Gives a pod a stable internal IP address that only other pods inside the cluster can reach. Used for Flask and Postgres — they should never be directly accessible from outside.
NodePort — exposes a service on a port on the host machine (e.g. port 30080). Used for Nginx — it is the only pod that the outside world should be able to reach.

Ingress vs Egress (NetworkPolicy context)

Ingress — traffic coming IN to a pod. A database ingress rule controls who is allowed to send data to Postgres.
Egress — traffic going OUT from a pod. A frontend egress rule controls where Nginx is allowed to send requests.

Why Calico?
Kubernetes has a NetworkPolicy API built in, but the default networking plugins (like kindnet or flannel) do not enforce those policies. Calico is a CNI plugin that actually reads and enforces NetworkPolicy rules. Without a CNI like Calico, you can write all the policies you want and they will simply be ignored.
DNS and NetworkPolicies
CoreDNS (the cluster's internal DNS server) lives in the kube-system namespace. When a pod tries to resolve a service name like flask-service.backend.svc.cluster.local, it sends a DNS query to CoreDNS on port 53. If your NetworkPolicy doesn't explicitly allow egress to kube-system on port 53, Calico blocks those DNS queries and all hostname-based connections fail — even if the actual service connection would be allowed. Always include a DNS egress rule in your policies.

Last updated: April 2026
Environment: Minikube v1.33.x · Kubernetes v1.35.1 · Calico (kube-system) · Ubuntu 24.04# k8s-security-lab
