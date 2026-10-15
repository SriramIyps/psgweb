
  var token = sessionStorage.getItem('psg_token');
  var role  = sessionStorage.getItem('psg_role');
  if (!token || role !== 'hr') { window.location.href = 'login.html'; }

  document.getElementById('user-info').textContent = sessionStorage.getItem('psg_email');
  document.getElementById('btn-logout').addEventListener('click', function() { sessionStorage.clear(); window.location.href = 'login.html'; });

  function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function toast(msg, type) { var t = document.getElementById('toast'); t.textContent = msg; t.className = 'toast show toast-' + (type||'info'); setTimeout(function(){ t.className = 'toast'; }, 3000); }

  async function api(path, opts) {
    opts = opts || {};
    var res = await fetch(path, Object.assign({}, opts, {
      headers: Object.assign({ 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    if (res.status === 401) { sessionStorage.clear(); window.location.href = 'login.html'; }
    return res;
  }

  async function loadApps() {
    var wrap = document.getElementById('table-wrap');
    var q = document.getElementById('search-input').value;
    var url = '/api/hr/applications?';
    if (q) url += 'q=' + encodeURIComponent(q) + '&';

    try {
      var res = await api(url);
      var data = await res.json();
      var apps = data.applications || [];

      document.getElementById('s-total').textContent = apps.length;
      document.getElementById('count-label').textContent = '(' + apps.length + ')';

      if (!apps.length) {
        wrap.innerHTML = '<div class="empty-state"><i class="fa-solid fa-inbox"></i>No shortlisted forwarded candidates available yet.</div>';
        return;
      }

      var html = '<table><thead><tr><th>#</th><th>App Ref</th><th>Name</th><th>Position</th><th>Department</th><th>Email</th><th>Mobile</th><th>Actions</th></tr></thead><tbody>';
      apps.forEach(function(a, i) {
        html += '<tr><td>' + (i+1) + '</td>';
        html += '<td style="font-weight:600;">' + esc(a.app_uuid||'—') + '</td>';
        html += '<td style="font-weight:600;">' + esc(a.name||'—') + '</td>';
        html += '<td>' + esc(a.position||'—') + '</td>';
        html += '<td>' + esc(a.department||'—') + '</td>';
        html += '<td>' + esc(a.email||'—') + '</td>';
        html += '<td>' + esc(a.mobile_no||'—') + '</td>';
        html += '<td><button class="btn-view" onclick="viewApp(' + a.id + ')">View</button></td></tr>';
      });
      html += '</tbody></table>';
      wrap.innerHTML = html;
    } catch(e) { console.error(e); }
  }

  async function viewApp(id) {
    try {
      var res = await api('/api/applications/' + id);
      if (!res.ok) { toast('Failed to load candidate details', 'error'); return; }
      var app = await res.json();
      document.getElementById('modal-title').textContent = (app.name||'Candidate') + ' — ' + (app.position||'');
      
      var fields = {
        'Application Info': ['app_uuid','position','department','submitted_at'],
        'Personal Details': ['name','dob','gender','email','mobile_no','father_name','category','community','native_city','native_state'],
        'Academic Summary': ['achivements','net','set_slet'],
        'Research Summary': ['sci','scopus','ugc','h_index_google','h_index_scopus']
      };
      
      var html = '';
      for (var sec in fields) {
        html += '<div class="dsec-title">' + sec + '</div><div class="dfgrid">';
        fields[sec].forEach(function(k) {
          var val = app[k] !== undefined && app[k] !== null ? String(app[k]) : '—';
          html += '<div class="dfield"><label>' + k.replace(/_/g,' ') + '</label><div class="val">' + esc(val) + '</div></div>';
        });
        html += '</div>';
      }
      if (app.resume_path) html += '<div class="dsec-title">Files</div><a href="' + app.resume_path + '" target="_blank" class="file-link">📄 View Resume</a>';
      document.getElementById('modal-body').innerHTML = html;
      document.getElementById('detail-overlay').classList.add('active');
    } catch(e) { toast('Error loading candidate', 'error'); }
  }

  async function exportHRCSV() {
    try {
      var res = await fetch('/api/hr/shortlisted-csv', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!res.ok) { toast('No HR shortlisted data to export', 'info'); return; }
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a'); a.href = url; a.download = 'HR_Shortlisted_Candidates.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch(e) { toast('CSV Export failed: ' + e, 'error'); }
  }

  ['modal-close','modal-cancel'].forEach(function(id) {
    document.getElementById(id).addEventListener('click', function() { document.getElementById('detail-overlay').classList.remove('active'); });
  });
  document.getElementById('detail-overlay').addEventListener('click', function(e) { if(e.target===e.currentTarget) e.currentTarget.classList.remove('active'); });

  loadApps();
