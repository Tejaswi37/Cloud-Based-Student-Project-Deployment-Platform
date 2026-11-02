# Cloud-Based Student Project Deployment Platform

Flask student portal for account registration, project ZIP submission, project listing and download. Includes Docker and Kubernetes configuration.

## Run locally (Windows PowerShell)
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```
Open http://localhost:5000

## Run with Docker
```powershell
docker compose up --build
```
Open http://localhost:5000. Stop with `docker compose down`.

## Run on Minikube
```powershell
minikube start --driver=docker
minikube image build -t student-platform:latest .
kubectl apply -f kubernetes/pvc.yaml
kubectl apply -f kubernetes/deployment.yaml
kubectl apply -f kubernetes/service.yaml
kubectl get pods
kubectl get services
minikube service student-platform-service
```

## Notes
This example uses one Kubernetes replica because it uses SQLite and pod-local upload storage. For multiple replicas, replace SQLite with PostgreSQL and use shared object storage. Before public production deployment, configure a strong secret, HTTPS, a production WSGI server, CSRF protection, backups and access controls.
