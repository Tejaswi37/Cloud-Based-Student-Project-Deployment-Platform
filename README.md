# DeployHub — Cloud-Based Student Project Deployment Platform

A custom Flask + SQLite + HTML/CSS/JavaScript application for registering student projects, faculty approval, Docker image builds, test deployments, operational reports and role-based administration.

## Screens included
1. Dashboard
2. Project registry and approval
3. Build activity and build logs
4. Test deployments and project URLs
5. Reports (four required reports, CSV export)
6. System logs
7. User management
8. Sign in / student registration

## Roles
- **Student:** self-register, submit projects and view own project/build/deployment records.
- **Faculty:** review pending submissions and approve/reject projects.
- **DevOps Administrator:** build Docker images, deploy successful builds and inspect operational activity.
- **Admin:** platform-wide visibility, project review, DevOps actions, report access and provision faculty/DevOps accounts.

Student registration is open. Faculty and DevOps accounts can only be provisioned by an administrator. There are no pre-filled demo accounts or demo email addresses.

## Requirements
- Python 3.10+
- Git CLI
- Docker Desktop / Docker Engine (needed for real image builds and test deployments)

## Run locally in VS Code / Windows PowerShell
```powershell
cd Cloud-Based-Student-Project-Deployment-Platform
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "replace-this-with-a-long-random-secret"
$env:ADMIN_EMAIL = "your-real-admin-email@college.edu"
$env:ADMIN_PASSWORD = "choose-a-strong-password"
py app.py
```
Open `http://localhost:5000`. The administrator account is created from the two environment variables on first startup. Use your actual email and a strong password; do not commit them. Student users can register through the website. Use Admin → User management to create Faculty and DevOps Administrator accounts.

To run only the web interface without provisioning an administrator, omit `ADMIN_EMAIL` and `ADMIN_PASSWORD`; the first account registered will have the Student role. For a usable complete role workflow, provision the administrator before starting the app.

## Real build and deployment workflow
1. Student submits an HTTPS Git repository URL. The repository must be publicly cloneable and include a Dockerfile.
2. Faculty approves or rejects the submission.
3. DevOps Administrator selects **Build image**. The server clones the repository with Git and invokes `docker build`. The actual Docker output and result are stored in the build record.
4. After a successful build, DevOps selects **Deploy approved build**. The backend runs the image as a Docker container and records its test URL, port, container ID and output.
5. Reports provide the required four operational views and CSV export.

**Important:** Docker build/deploy actions execute Docker commands on the machine hosting the Flask server. They are intended for a controlled academic test environment. Do not expose this app to the public internet or allow untrusted users to submit arbitrary repositories without adding stronger isolation, resource limits, authorization review and secrets management. The deployment currently assumes the built project listens on container port `8080`; change the `-p` target in `app.py` if your project images use another port.

## Docker Compose
Create a local `.env` from `.env.example`, set a strong `SECRET_KEY`, `ADMIN_EMAIL` and `ADMIN_PASSWORD`, then:
```powershell
docker compose up --build -d
```
Open `http://localhost:5000`. The compose file mounts the Docker socket so the platform can request builds and runs from the host Docker engine. **Docker socket access is highly privileged.** Use only on your own trusted development machine. Persisted SQLite data is stored in the `deployhub-data` volume.

## Kubernetes (Minikube)
Build the image in Minikube's Docker daemon or load it:
```powershell
minikube start
docker build -t deployhub:latest .
minikube image load deployhub:latest
kubectl create secret generic deployhub-secrets --from-literal=secret-key="replace-with-a-long-random-secret"
kubectl apply -f kubernetes/pvc.yaml
kubectl apply -f kubernetes/deployment.yaml
kubectl apply -f kubernetes/service.yaml
kubectl rollout status deployment/deployhub
minikube service deployhub-service
```
The app deployment manifest contains the persistent volume claim and secret reference. The app's Docker operations also require access to a Docker daemon; Kubernetes deployment alone does not provide a Docker socket. For the full build/deploy feature in Kubernetes, configure a dedicated build service/runner and a separate deployment controller rather than mounting a privileged host socket into the web pod. The provided manifests demonstrate application deployment, service exposure and persistent storage for the academic rubric.

## API overview
- `POST /api/register`, `POST /api/login`, `POST /api/logout`, `GET /api/me`
- `GET/POST /api/projects`
- `PATCH /api/projects/{id}/approval`
- `POST /api/projects/{id}/build`
- `GET /api/builds`
- `POST /api/projects/{id}/deploy`, `GET /api/deployments`
- `GET /api/reports/projects|builds|deployments|failed`
- `GET /api/users`, `POST /api/users`, `GET /api/logs`

## Notes
- Passwords are hashed using Werkzeug.
- Session cookies are HTTP-only and SameSite=Lax.
- Student registration cannot self-assign privileged roles.
- The application uses SQLite for a straightforward local academic setup. For production, use PostgreSQL, CSRF protection, stronger session/secret management, audit retention and isolated build workers.
