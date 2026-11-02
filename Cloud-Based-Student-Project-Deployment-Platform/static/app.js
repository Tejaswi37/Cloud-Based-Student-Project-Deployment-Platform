const el=id=>document.getElementById(id), msg=el("message");
function message(t,error=false){msg.textContent=t;msg.classList.remove("hidden","error");if(error)msg.classList.add("error")}
async function api(url,options={}){const r=await fetch(url,{...options,credentials:"same-origin"});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d}
function dashboard(name){el("auth").classList.add("hidden");el("dashboard").classList.remove("hidden");el("logout").classList.remove("hidden");el("student").textContent=name;loadProjects()}
function auth(){el("auth").classList.remove("hidden");el("dashboard").classList.add("hidden");el("logout").classList.add("hidden")}
async function submitAuth(form,url){const data=Object.fromEntries(new FormData(form));try{const d=await api(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});dashboard(d.name);message(d.message)}catch(e){message(e.message,true)}}
el("login").onsubmit=e=>{e.preventDefault();submitAuth(e.target,"/api/login")};
el("register").onsubmit=e=>{e.preventDefault();submitAuth(e.target,"/api/register")};
el("upload").onsubmit=async e=>{e.preventDefault();try{const d=await api("/api/projects",{method:"POST",body:new FormData(e.target)});e.target.reset();message(d.message);loadProjects()}catch(x){message(x.message,true)}};
el("logout").onclick=async()=>{await api("/api/logout",{method:"POST"});auth();message("Logged out.")};
el("refresh").onclick=loadProjects;
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
async function loadProjects(){try{const items=await api("/api/projects");el("projects").innerHTML=items.length?items.map(p=>`<article class="project"><b>${esc(p.title)}</b><p>${esc(p.description)}</p><p>Technology: ${esc(p.technology)}</p><span class="tag">${esc(p.status)}</span><p><a href="/api/projects/${p.id}/download">Download ZIP</a></p></article>`).join(""):"<p class='muted'>No projects submitted yet.</p>"}catch(e){el("projects").textContent=e.message}}
(async()=>{try{const d=await api("/api/me");d.logged_in?dashboard(d.name):auth()}catch(e){auth()}})();
