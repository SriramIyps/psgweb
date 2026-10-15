
  var token = sessionStorage.getItem('psg_token');
  var role  = sessionStorage.getItem('psg_role');
  if (!token || role !== 'hod') { window.location.href = 'login.html'; }

  document.getElementById('user-info').textContent = sessionStorage.getItem('psg_email');
  document.getElementById('btn-logout').addEventListener('click', function() { sessionStorage.clear(); window.location.href = 'login.html'; });

  function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function toast(msg, type) { var t = document.getElementById('toast'); t.textContent = msg; t.className = 'toast show toast-' + (type||'info'); setTimeout(function(){ t.className = 'toast'; }, 3500); }

  async function api(path, opts) {
    opts = opts || {};
    var res = await fetch(path, Object.assign({}, opts, {
      headers: Object.assign({ 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }, opts.headers || {})
    }));
    if (res.status === 401) { sessionStorage.clear(); window.location.href = 'login.html'; }
    return res;
  }

  var currentHodData = null;

  async function loadDashboard() {
    try {
      var res = await api('/api/hod/applications');
      var data = await res.json();
      if (!res.ok) {
        toast(data.error || 'Failed to load dashboard', 'error');
        return;
      }
      currentHodData = data;

      document.getElementById('dept-badge').textContent = 'HOD — ' + (data.department || '');
      document.getElementById('dept-title').textContent = 'Department of ' + (data.department || '') + ' — Scrutiny';

      var bannerHtml = '';
      if (data.portal_open) {
        bannerHtml = '<div class="banner banner-warning">' +
          '<div><div class="banner-title"><i class="fa-solid fa-lock"></i> Application Portal is Open</div>' +
          '<div class="banner-desc">Candidate application window closes on <strong>' + esc(data.close_date) + '</strong>. HOD scrutiny opens immediately after the deadline.</div></div>' +
          '</div>';
        document.getElementById('status-banner').innerHTML = bannerHtml;
        document.getElementById('stats-container').style.display = 'none';
        document.getElementById('action-bar').style.display = 'none';
        document.getElementById('table-container').style.display = 'none';
        return;
      }

      if (data.is_forwarded) {
        var fDate = data.forwarded_at ? new Date(data.forwarded_at).toLocaleString('en-IN') : '';
        bannerHtml = '<div class="banner banner-success">' +
          '<div><div class="banner-title"><i class="fa-solid fa-circle-check"></i> Scrutiny Complete & Forwarded to Vice Principal</div>' +
          '<div class="banner-desc">Forwarded on <strong>' + esc(fDate) + '</strong> by <strong>' + esc(data.forwarded_by||'') + '</strong>. Applications for this department are locked for further HOD edits.</div></div>' +
          '</div>';
      } else {
        var pCount = data.stats.pending_count;
        if (pCount > 0) {
          bannerHtml = '<div class="banner banner-info">' +
            '<div><div class="banner-title"><i class="fa-solid fa-list-check"></i> Scrutiny In Progress</div>' +
            '<div class="banner-desc"><strong>' + pCount + '</strong> application(s) pending scrutiny decision. Complete all reviews to enable forwarding to Vice Principal.</div></div>' +
            '</div>';
        } else {
          bannerHtml = '<div class="banner banner-success">' +
            '<div><div class="banner-title"><i class="fa-solid fa-check-double"></i> All Applications Scrutinised</div>' +
            '<div class="banner-desc">All submitted candidates have been reviewed. Click "Forward Department to Vice Principal" below to finalize.</div></div>' +
            '</div>';
        }
      }
      document.getElementById('status-banner').innerHTML = bannerHtml;

      // Stats & Progress line
      document.getElementById('stats-container').style.display = 'grid';
      document.getElementById('action-bar').style.display = 'flex';
      document.getElementById('table-container').style.display = 'block';

      var totalSub = data.stats.total_submitted;
      var pendCount = data.stats.pending_count;
      var scrutinisedCount = totalSub - pendCount;

      document.getElementById('s-total').textContent = totalSub;
      document.getElementById('s-pending').textContent = pendCount;
      document.getElementById('s-eligible').textContent = data.stats.eligible_count;
      document.getElementById('s-not-eligible').textContent = data.stats.not_eligible_count;
      document.getElementById('progress-line').textContent = 'Progress: ' + scrutinisedCount + ' of ' + totalSub + ' scrutinised';

      // Forward button state
      var fBtn = document.getElementById('btn-forward-dept');
      if (data.can_forward) {
        fBtn.className = 'btn btn-forward';
        fBtn.disabled = false;
      } else {
        fBtn.className = 'btn btn-forward btn-disabled';
        fBtn.disabled = true;
      }

      applyFilters();

    } catch(e) {
      console.error(e);
      toast('Error loading dashboard data', 'error');
    }
  }

  function applyFilters() {
    if (!currentHodData || !currentHodData.applications) return;
    var q = (document.getElementById('search-input').value || '').toLowerCase().trim();
    var st = document.getElementById('filter-status').value;

    var filtered = currentHodData.applications.filter(function(a) {
      var matchQ = !q || (a.name || '').toLowerCase().includes(q) || (a.app_uuid || '').toLowerCase().includes(q);
      var matchSt = !st || (a.hod_status || 'Pending') === st;
      return matchQ && matchSt;
    });

    renderTable(filtered, currentHodData.is_forwarded);
  }

  function renderTable(apps, isForwarded) {
    var wrap = document.getElementById('table-wrap');
    document.getElementById('count-label').textContent = '(' + apps.length + ')';

    if (!apps.length) {
      wrap.innerHTML = '<div class="empty-state"><i class="fa-solid fa-folder-open"></i>No applications match your search or filter criteria.</div>';
      return;
    }

    var html = '<table><thead><tr><th>#</th><th>App Ref</th><th>Candidate Name</th><th>Position</th><th>Qualification</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
    apps.forEach(function(a, i) {
      var st = a.hod_status || 'Pending';
      var stClass = {'Pending':'s-pending','Eligible':'s-eligible','Not Eligible':'s-not-eligible'}[st] || 's-pending';
      
      var eduStr = '—';
      try {
        var eduRaw = a.education;
        var eduList = typeof eduRaw === 'string' ? JSON.parse(eduRaw) : (eduRaw || []);
        if (Array.isArray(eduList) && eduList.length) {
          eduStr = eduList.map(function(e){ return esc(e.degree||e.qualification); }).join(', ');
        }
      } catch(e){}

      html += '<tr><td>' + (i+1) + '</td>';
      html += '<td style="font-weight:600;">' + esc(a.app_uuid||'—') + '</td>';
      html += '<td style="font-weight:600;">' + esc(a.name||'—') + '<br/><span style="font-size:.75rem;font-weight:400;color:#64748b;">' + esc(a.email||'') + '</span></td>';
      html += '<td>' + esc(a.position||'—') + '</td>';
      html += '<td>' + esc(eduStr) + '</td>';
      html += '<td><span class="status-badge ' + stClass + '">' + esc(st) + '</span></td>';
      html += '<td><div class="act-btns">';
      html += '<button class="btn-sm btn-view" onclick="viewApp(' + a.id + ')">View</button>';
      
      if (!isForwarded) {
        html += '<button class="btn-sm btn-elig" onclick="markEligible(' + a.id + ')">✓ Eligible</button>';
        html += '<button class="btn-sm btn-not-elig" onclick="openRejectModal(' + a.id + ')">✗ Not Eligible</button>';
      }
      
      html += '</div></td></tr>';
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;
  }

  async function downloadReport(path, type) {
    try {
      var res = await fetch(path, { headers: { 'Authorization': 'Bearer ' + token } });
      if (!res.ok) {
        var errData = await res.json().catch(function(){ return {}; });
        toast(errData.error || 'Report generation failed', 'error');
        return;
      }
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      if (type === 'csv') {
        var a = document.createElement('a');
        a.href = url;
        a.download = path.split('/').pop().replace('.csv','') + '.csv';
        a.click();
        URL.revokeObjectURL(url);
      } else {
        window.open(url, '_blank');
      }
    } catch(e) {
      toast('Error downloading report', 'error');
    }
  }

  async function markEligible(id) {
    if (!confirm('Mark candidate as Eligible?')) return;
    try {
      var res = await api('/api/applications/' + id + '/hod-review', {
        method: 'PUT',
        body: JSON.stringify({ hod_status: 'Eligible', hod_remarks: 'Verified per UGC norms' })
      });
      var data = await res.json();
      if (res.ok) {
        toast('Marked as Eligible', 'success');
        loadDashboard();
      } else {
        toast(data.error || 'Operation failed', 'error');
      }
    } catch(e) {
      toast('Error updating status', 'error');
    }
  }

  function openRejectModal(id) {
    document.getElementById('reject-app-id').value = id;
    document.getElementById('reject-remarks').value = '';
    document.getElementById('reject-overlay').classList.add('active');
  }

  function closeRejectModal() {
    document.getElementById('reject-overlay').classList.remove('active');
  }

  async function submitNotEligible() {
    var id = document.getElementById('reject-app-id').value;
    var remarks = document.getElementById('reject-remarks').value.trim();
    if (!remarks) {
      toast('Remarks/reason is mandatory when marking Not Eligible', 'error');
      return;
    }

    try {
      var res = await api('/api/applications/' + id + '/hod-review', {
        method: 'PUT',
        body: JSON.stringify({ hod_status: 'Not Eligible', hod_remarks: remarks })
      });
      var data = await res.json();
      if (res.ok) {
        toast('Marked as Not Eligible', 'success');
        closeRejectModal();
        loadDashboard();
      } else {
        toast(data.error || 'Operation failed', 'error');
      }
    } catch(e) {
      toast('Error updating status', 'error');
    }
  }

  async function forwardDepartment() {
    if (!confirm('Are you sure you want to forward this department scrutiny list to the Vice Principal? This action will lock all further HOD edits.')) return;

    try {
      var res = await api('/api/hod/forward', { method: 'POST' });
      var data = await res.json();
      if (res.ok) {
        toast(data.message || 'Department forwarded successfully!', 'success');
        loadDashboard();
      } else {
        toast(data.error || 'Forwarding failed', 'error');
      }
    } catch(e) {
      toast('Error forwarding department', 'error');
    }
  }

  async function downloadScrutinyPdf() {
    try {
      var res = await fetch('/api/hod/scrutiny-pdf', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!res.ok) { toast('PDF report download failed', 'error'); return; }
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    } catch(e) { toast('Error downloading PDF', 'error'); }
  }

  async function downloadEligibleCsv() {
    try {
      var res = await fetch('/api/hod/eligible-csv', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!res.ok) { toast('CSV export failed', 'error'); return; }
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a'); a.href = url; a.download = 'Eligible_Candidates.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch(e) { toast('Error exporting CSV', 'error'); }
  }

  async function viewApp(id) {
    try {
      var res = await api('/api/applications/' + id);
      if (!res.ok) { toast('Failed to load details', 'error'); return; }
      var app = await res.json();

      var rRes = await api('/api/applications/' + id + '/research');
      var rData = rRes.ok ? await rRes.json() : { counts: {}, publications: [], patents: [], consultancy: [], projects: [] };
      var c = rData.counts || {};

      document.getElementById('modal-title').textContent = (app.name||'Applicant') + ' — ' + (app.position||'');

      var html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:.75rem; padding:1rem; margin-bottom:1.25rem;">';
      html += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:.75rem;">';
      html += '<h4 style="font-size:.9rem; font-weight:700; color:#002e5b;">📊 Research Summary Counts</h4>';
      html += '<button onclick="downloadCandidatePdf(' + id + ')" style="background:#002e5b; color:#fff; padding:.35rem .85rem; border-radius:.375rem; border:none; font-weight:600; font-size:.75rem; cursor:pointer;">📥 Biodata PDF</button>';
      html += '</div>';
      html += '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(110px, 1fr)); gap:.5rem; text-align:center;">';
      html += '<div style="background:#fff; padding:.5rem; border-radius:.5rem; border:1px solid #cbd5e1;"><div style="font-size:1.1rem; font-weight:800; color:#7b1c1c;">' + (c.sci||0) + '</div><div style="font-size:.68rem; color:#64748b;">SCI Papers</div></div>';
      html += '<div style="background:#fff; padding:.5rem; border-radius:.5rem; border:1px solid #cbd5e1;"><div style="font-size:1.1rem; font-weight:800; color:#2563eb;">' + (c.scopus||0) + '</div><div style="font-size:.68rem; color:#64748b;">Scopus Papers</div></div>';
      html += '<div style="background:#fff; padding:.5rem; border-radius:.5rem; border:1px solid #cbd5e1;"><div style="font-size:1.1rem; font-weight:800; color:#059669;">' + (c.ugc_other||0) + '</div><div style="font-size:.68rem; color:#64748b;">UGC / Other</div></div>';
      html += '<div style="background:#fff; padding:.5rem; border-radius:.5rem; border:1px solid #cbd5e1;"><div style="font-size:1.1rem; font-weight:800; color:#d97706;">' + ((c.books||0)+(c.chapters||0)) + '</div><div style="font-size:.68rem; color:#64748b;">Books/Chapters</div></div>';
      html += '<div style="background:#fff; padding:.5rem; border-radius:.5rem; border:1px solid #cbd5e1;"><div style="font-size:1.1rem; font-weight:800; color:#7c3aed;">' + ((c.patents_published||0)+(c.patents_granted||0)) + '</div><div style="font-size:.68rem; color:#64748b;">Patents</div></div>';
      html += '<div style="background:#fff; padding:.5rem; border-radius:.5rem; border:1px solid #cbd5e1;"><div style="font-size:1.1rem; font-weight:800; color:#0891b2;">' + ((c.projects_major||0)+(c.projects_minor||0)) + '</div><div style="font-size:.68rem; color:#64748b;">Projects</div></div>';
      html += '</div></div>';

      var sections = {
        'Application Ref': ['app_uuid','position','department'],
        'Personal Details': ['name','dob','gender','email','mobile_no','father_name'],
        'HOD Scrutiny': ['hod_status','hod_remarks','hod_reviewed_at']
      };

      for (var sec in sections) {
        html += '<div style="font-size:.72rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:#94a3b8; margin:1rem 0 .5rem;">' + sec + '</div><div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:.75rem;">';
        sections[sec].forEach(function(k) {
          var val = app[k] !== undefined && app[k] !== null ? String(app[k]) : '—';
          html += '<div><label style="font-size:.72rem; color:#94a3b8; display:block;">' + k.replace(/_/g,' ') + '</label><div style="font-size:.875rem; color:#1e293b; font-weight:500;">' + esc(val) + '</div></div>';
        });
        html += '</div>';
      }

      if (app.resume_path) html += '<div style="margin-top:1rem;"><a href="' + app.resume_path + '" target="_blank" style="color:var(--maroon); font-weight:600;">📄 View Resume</a></div>';
      document.getElementById('modal-body').innerHTML = html;
      document.getElementById('detail-overlay').classList.add('active');
    } catch(e) { toast('Error loading details', 'error'); }
  }

  async function downloadCandidatePdf(id) {
    try {
      var res = await fetch('/api/applications/' + id + '/pdf', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!res.ok) { toast('PDF generation failed', 'error'); return; }
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    } catch(e) { toast('Error downloading PDF', 'error'); }
  }

  function closeDetailModal() {
    document.getElementById('detail-overlay').classList.remove('active');
  }

  loadDashboard();
