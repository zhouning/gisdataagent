"""
Result Sharing module — public link generation, validation, and file serving.
"""
import json
import os
import secrets
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import T_SHARE_LINKS
from .auth import _make_password_hash, _verify_password
from .user_context import current_user_id

_BASE_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

SHAPEFILE_SIDECARS = (".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml")


def ensure_share_links_table():
    """Create share_links table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[Sharing] WARNING: Database not configured. Sharing disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_SHARE_LINKS} (
                    id SERIAL PRIMARY KEY,
                    token VARCHAR(16) UNIQUE NOT NULL,
                    owner_username VARCHAR(100) NOT NULL,
                    title VARCHAR(300) DEFAULT '',
                    summary TEXT DEFAULT '',
                    files JSONB NOT NULL DEFAULT '[]',
                    pipeline_type VARCHAR(30),
                    password_hash VARCHAR(500),
                    expires_at TIMESTAMP,
                    view_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_share_links_token ON {T_SHARE_LINKS} (token)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_share_links_owner ON {T_SHARE_LINKS} (owner_username)"
            ))
            conn.commit()
        print("[Sharing] Share links table ready.")
    except Exception as e:
        print(f"[Sharing] Error initializing share_links table: {e}")


def create_share_link(
    title: str,
    summary: str,
    files: list,
    pipeline_type: str,
    password: Optional[str] = None,
    expires_hours: Optional[int] = None,
) -> dict:
    """Generate a shareable link for analysis results.

    Args:
        title: Share title (user's question or custom).
        summary: Markdown report text.
        files: List of dicts [{"filename": "map.html", "type": "html"}, ...].
        pipeline_type: Pipeline that produced the results.
        password: Optional access password (min 4 chars).
        expires_hours: Hours until link expires. None = never.

    Returns:
        {"status": "success", "token": "...", "url": "/s/..."} or error dict.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    owner = current_user_id.get()
    if not owner or owner == "anonymous":
        return {"status": "error", "message": "User not authenticated"}

    token = secrets.token_urlsafe(12)  # 16-char URL-safe string

    pw_hash = None
    if password:
        if len(password) < 4:
            return {"status": "error", "message": "Password must be at least 4 characters"}
        pw_hash = _make_password_hash(password)

    files_json = json.dumps(files, ensure_ascii=False)

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_SHARE_LINKS}
                    (token, owner_username, title, summary, files, pipeline_type,
                     password_hash, expires_at)
                VALUES (
                    :token, :owner, :title, :summary, CAST(:files AS jsonb), :pipeline,
                    :pw_hash,
                    CASE WHEN :hours IS NOT NULL
                         THEN NOW() + make_interval(hours => CAST(:hours AS int))
                         ELSE NULL END
                )
            """), {
                "token": token, "owner": owner, "title": title[:300],
                "summary": summary, "files": files_json,
                "pipeline": pipeline_type, "pw_hash": pw_hash,
                "hours": expires_hours,
            })
            conn.commit()
        return {"status": "success", "token": token, "url": f"/s/{token}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to create share link: {e}"}


def validate_share_token(token: str, password: Optional[str] = None) -> dict:
    """Validate a share token and return share data.

    Returns:
        On success: {"status": "success", "data": {...}}
        On error: {"status": "error", "reason": "not_found|expired|password_required|wrong_password"}
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "reason": "not_found"}

    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT owner_username, title, summary, files, pipeline_type,
                       password_hash, expires_at, view_count, created_at,
                       CASE WHEN expires_at IS NOT NULL AND expires_at < NOW()
                            THEN TRUE ELSE FALSE END AS is_expired
                FROM {T_SHARE_LINKS} WHERE token = :t
            """), {"t": token}).fetchone()

            if not row:
                return {"status": "error", "reason": "not_found"}

            owner, title, summary, files_data, pipeline_type, \
                pw_hash, expires_at, view_count, created_at, is_expired = row

            # Check expiry (compared server-side to avoid timezone mismatch)
            if is_expired:
                return {"status": "error", "reason": "expired"}

            # Check password
            if pw_hash is not None:
                if password is None:
                    return {"status": "error", "reason": "password_required"}
                if not _verify_password(password, pw_hash):
                    return {"status": "error", "reason": "wrong_password"}

            # Increment view count
            conn.execute(text(
                f"UPDATE {T_SHARE_LINKS} SET view_count = view_count + 1 WHERE token = :t"
            ), {"t": token})
            conn.commit()

            # Parse files if needed
            if isinstance(files_data, str):
                files_data = json.loads(files_data)

            return {
                "status": "success",
                "data": {
                    "owner": owner,
                    "title": title,
                    "summary": summary,
                    "files": files_data,
                    "pipeline_type": pipeline_type,
                    "created_at": created_at.isoformat() if created_at else None,
                    "view_count": view_count + 1,
                },
            }
    except Exception as e:
        return {"status": "error", "reason": "not_found", "message": str(e)}


def get_share_file_path(token: str, filename: str) -> Optional[str]:
    """Resolve a file path for a share link, with security validation.

    Returns the absolute file path if valid, or None.
    """
    # Reject path traversal
    if '..' in filename or '/' in filename or '\\' in filename or '\0' in filename:
        return None

    engine = get_engine()
    if not engine:
        return None

    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT owner_username, files,
                       CASE WHEN expires_at IS NOT NULL AND expires_at < NOW()
                            THEN TRUE ELSE FALSE END AS is_expired
                FROM {T_SHARE_LINKS} WHERE token = :t
            """), {"t": token}).fetchone()

            if not row:
                return None

            owner, files_data, is_expired = row

            # Check expiry (compared server-side to avoid timezone mismatch)
            if is_expired:
                return None

            # Parse files
            if isinstance(files_data, str):
                files_data = json.loads(files_data)

            # Whitelist check
            allowed = {f["filename"] for f in files_data}
            if filename not in allowed:
                return None

            # Build and validate path
            full_path = os.path.join(_BASE_UPLOAD_DIR, owner, filename)
            abs_path = os.path.realpath(full_path)
            allowed_dir = os.path.realpath(os.path.join(_BASE_UPLOAD_DIR, owner))
            if not abs_path.startswith(allowed_dir + os.sep) and abs_path != allowed_dir:
                return None

            if not os.path.exists(abs_path):
                return None

            return abs_path
    except Exception:
        return None


def delete_share_link(token: str) -> dict:
    """Delete a share link. Only the owner can delete."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    owner = current_user_id.get()
    if not owner or owner == "anonymous":
        return {"status": "error", "message": "User not authenticated"}

    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"DELETE FROM {T_SHARE_LINKS} WHERE token = :t AND owner_username = :o"
            ), {"t": token, "o": owner})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "Link not found or access denied"}
            return {"status": "success", "message": "Share link deleted"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def expand_shapefile_sidecars(files_list: list) -> list:
    """For any .shp in files_list, add sidecar files (.dbf, .shx, .prj, .cpg) if they exist."""
    result = list(files_list)
    existing_names = {f["filename"] for f in result}

    for f in list(files_list):
        if f["filename"].lower().endswith(".shp"):
            base = f["filename"][:-4]
            for ext in SHAPEFILE_SIDECARS:
                sidecar_name = base + ext
                if sidecar_name not in existing_names:
                    result.append({"filename": sidecar_name, "type": ext.lstrip(".")})
                    existing_names.add(sidecar_name)

    return result


# ---------------------------------------------------------------------------
# Share Viewer HTML Template
# ---------------------------------------------------------------------------

SHARE_VIEWER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>分析结果分享 — Data Agent</title>
<script src="https://cdn.bootcdn.net/ajax/libs/marked/12.0.1/marked.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     background:#f5f5f5;color:#333;line-height:1.6}
.container{max-width:960px;margin:0 auto;padding:24px 16px}
header{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;
       box-shadow:0 1px 3px rgba(0,0,0,.1)}
header h1{font-size:1.4em;color:#1a1a2e;margin-bottom:8px}
.meta{font-size:.85em;color:#888}
.section{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;
         box-shadow:0 1px 3px rgba(0,0,0,.1)}
.section h2{font-size:1.1em;color:#16213e;margin-bottom:12px;
            border-bottom:2px solid #e8e8e8;padding-bottom:8px}
.summary-content{line-height:1.8}
.summary-content table{border-collapse:collapse;width:100%;margin:12px 0}
.summary-content th,.summary-content td{border:1px solid #ddd;padding:8px;text-align:left}
.summary-content th{background:#f8f8f8}
.map-frame{width:100%;height:600px;border:none;border-radius:8px;margin:8px 0}
.image-preview{max-width:100%;border-radius:8px;margin:8px 0}
.file-list{list-style:none;padding:0}
.file-list li{padding:10px 12px;border:1px solid #eee;border-radius:8px;margin:6px 0}
.file-list a{color:#6366f1;text-decoration:none;font-weight:500}
.file-list a:hover{text-decoration:underline}
.file-type{display:inline-block;background:#e8e8ff;color:#6366f1;font-size:.75em;
           padding:2px 8px;border-radius:4px;margin-left:8px}
footer{text-align:center;color:#aaa;font-size:.8em;padding:24px 0}
footer a{color:#6366f1;text-decoration:none}
/* Password form */
.pw-box{max-width:400px;margin:80px auto;background:#fff;border-radius:12px;
        padding:40px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.pw-box h2{margin-bottom:16px;color:#1a1a2e}
.pw-box input{width:100%;padding:12px;border:1px solid #ddd;border-radius:8px;
              font-size:1em;margin-bottom:12px}
.pw-box button{width:100%;padding:12px;background:#6366f1;color:#fff;border:none;
               border-radius:8px;font-size:1em;cursor:pointer}
.pw-box button:hover{background:#4f46e5}
.pw-error{color:#e74c3c;font-size:.9em;margin-top:8px;display:none}
.error-box{max-width:500px;margin:80px auto;background:#fff;border-radius:12px;
           padding:40px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.error-box h2{color:#e74c3c;margin-bottom:12px}
#loading{text-align:center;padding:80px;color:#888;font-size:1.1em}
</style>
</head>
<body>
<div id="loading">加载中...</div>
<div id="password-form" class="pw-box" style="display:none">
  <h2>此链接需要密码访问</h2>
  <input type="password" id="pw-input" placeholder="请输入访问密码" autofocus>
  <button id="pw-submit">验证</button>
  <p class="pw-error" id="pw-error"></p>
</div>
<div id="error-page" class="error-box" style="display:none">
  <h2 id="error-title"></h2>
  <p id="error-msg"></p>
</div>
<div id="content" class="container" style="display:none">
  <header>
    <h1 id="share-title"></h1>
    <p class="meta" id="share-meta"></p>
  </header>
  <div class="section" id="summary-section">
    <h2>分析报告</h2>
    <div class="summary-content" id="share-summary"></div>
  </div>
  <div id="maps-section"></div>
  <div id="images-section"></div>
  <div id="downloads-section"></div>
  <footer>Powered by <a href="/">Data Agent</a></footer>
</div>
<script>
(function(){
  var TOKEN = window.location.pathname.replace('/s/','');
  var BASE = '/api/share/' + TOKEN;

  function show(id){document.getElementById(id).style.display='';}
  function hide(id){document.getElementById(id).style.display='none';}

  function showError(title, msg){
    hide('loading');
    document.getElementById('error-title').textContent = title;
    document.getElementById('error-msg').textContent = msg;
    show('error-page');
  }

  function renderContent(data){
    hide('loading'); hide('password-form');
    var d = data.data;
    document.title = (d.title || '分析结果') + ' — Data Agent';
    document.getElementById('share-title').textContent = d.title || '分析结果分享';
    var pipeLabels = {optimization:'空间布局优化',governance:'数据质量治理',
                      general:'空间数据分析',planner:'智能规划分析'};
    var meta = (pipeLabels[d.pipeline_type]||'分析') + ' · 分享于 ' +
               (d.created_at?new Date(d.created_at).toLocaleDateString('zh-CN'):'') +
               ' · 浏览 ' + d.view_count + ' 次';
    document.getElementById('share-meta').textContent = meta;

    if(d.summary){
      document.getElementById('share-summary').innerHTML = marked.parse(d.summary);
    } else {
      hide('summary-section');
    }

    var maps=[],images=[],others=[];
    (d.files||[]).forEach(function(f){
      if(f.type==='html') maps.push(f);
      else if(f.type==='png') images.push(f);
      else if(['dbf','shx','prj','cpg','sbn','sbx','shp.xml'].indexOf(f.type)===-1)
        others.push(f);
    });

    if(maps.length){
      var sec = document.getElementById('maps-section');
      maps.forEach(function(f){
        var div = document.createElement('div');
        div.className='section';
        div.innerHTML='<h2>交互地图: '+f.filename+'</h2>'+
          '<iframe class="map-frame" src="'+BASE+'/file/'+encodeURIComponent(f.filename)+'"></iframe>';
        sec.appendChild(div);
      });
    }
    if(images.length){
      var sec = document.getElementById('images-section');
      var div = document.createElement('div');
      div.className='section';
      div.innerHTML='<h2>分析图表</h2>';
      images.forEach(function(f){
        div.innerHTML+='<img class="image-preview" src="'+BASE+'/file/'+
          encodeURIComponent(f.filename)+'" alt="'+f.filename+'">';
      });
      sec.appendChild(div);
    }
    if(others.length){
      var sec = document.getElementById('downloads-section');
      var div = document.createElement('div');
      div.className='section';
      div.innerHTML='<h2>数据文件下载</h2><ul class="file-list"></ul>';
      var ul = div.querySelector('ul');
      others.forEach(function(f){
        var li = document.createElement('li');
        li.innerHTML='<a href="'+BASE+'/file/'+encodeURIComponent(f.filename)+
          '" download>'+f.filename+'</a><span class="file-type">'+f.type.toUpperCase()+'</span>';
        ul.appendChild(li);
      });
      sec.appendChild(div);
    }
    show('content');
  }

  function doValidate(pw){
    var opts = {method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({password:pw||null})};
    fetch(BASE+'/validate',opts).then(function(r){return r.json().then(function(j){return{s:r.status,d:j}})})
    .then(function(res){
      if(res.s===200){ renderContent(res.d); return; }
      if(res.d.reason==='password_required'){
        hide('loading'); show('password-form'); return;
      }
      if(res.d.reason==='wrong_password'){
        var e=document.getElementById('pw-error');
        e.textContent='密码错误，请重试'; e.style.display='';
        return;
      }
      if(res.d.reason==='expired') showError('链接已过期','此分享链接已超过有效期。');
      else showError('链接不存在','未找到此分享链接，请检查URL是否正确。');
    }).catch(function(){ showError('加载失败','网络错误，请稍后重试。'); });
  }

  document.getElementById('pw-submit').onclick = function(){
    var pw = document.getElementById('pw-input').value;
    if(!pw) return;
    doValidate(pw);
  };
  document.getElementById('pw-input').onkeydown = function(e){
    if(e.key==='Enter') document.getElementById('pw-submit').click();
  };

  doValidate(null);
})();
</script>
</body>
</html>"""
