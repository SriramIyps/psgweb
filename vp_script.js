
  var token = sessionStorage.getItem('psg_token');
  var role  = sessionStorage.getItem('psg_role');
  if (!token || role !== 'superadmin') { window.location.href = 'login.html'; }

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

  var deptForwardedMap = {};

  // Load departments with forwarding status
  async function loadDepartments() {
    try {
      var res = await api('/api/vp/departments');
      var data = await res.json();
      var sel = document.getElementById('filter-dept');
      var currentVal = sel.value;
      sel.innerHTML = '<option value="">All Departments</option>';
      (data.departments || []).forEach(function(d) {
        deptForwardedMap[d.department] = d;
        var o = document.createElement('option');
        o.value = d.department;
        var statusTag = '';
        if (d.is_vp_forwarded) {
          statusTag = ' [VP Forwarded to HR]';
        } else if (d.is_hod_forwarded || d.is_forwarded) {
          statusTag = ' [HOD Forwarded]';
        } else {
          statusTag = ' [Pending HOD Forward]';
        }
        o.textContent = d.department + statusTag;
        sel.appendChild(o);
      });
      sel.value = currentVal;
    } catch(e) {}
  }

  function onDeptChange() {
    updateDeptActionBar();
    loadApps();
  }

  function updateDeptActionBar() {
    var dept = document.getElementById('filter-dept').value;
    var bar = document.getElementById('dept-action-bar');
    if (!dept || !deptForwardedMap[dept]) {
      bar.style.display = 'none';
      return;
    }
    bar.style.display = 'flex';
    var d = deptForwardedMap[dept];
    document.getElementById('dept-title-text').textContent = 'Department of ' + d.department;

    var totalEligible = d.eligible_count || 0;
    var pendingVP = d.pending_vp_count || 0;
    var reviewedVP = (d.shortlisted_count || 0) + (d.not_shortlisted_count || 0);

    var progText = reviewedVP + ' of ' + totalEligible + ' eligible candidates reviewed';
    if (d.is_vp_forwarded) {
      progText += ' • <span style="color:#059669; font-weight:600;"><i class="fa-solid fa-circle-check"></i> Forwarded to HR (SF Office)</span>';
    } else if (!d.is_hod_forwarded && !d.is_forwarded) {
      progText += ' • <span style="color:#d97706; font-weight:600;"><i class="fa-solid fa-clock"></i> Pending HOD Forward</span>';
    }
    document.getElementById('dept-progress-text').innerHTML = progText;

    var btn = document.getElementById('btn-forward-hr');
    if (d.is_vp_forwarded) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-check-double"></i> Already Forwarded to HR';
      btn.title = 'This department has already been forwarded to HR.';
    } else if (!d.is_hod_forwarded && !d.is_forwarded) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Forward to HR (SF Office)';
      btn.title = 'HOD must forward scrutinised candidates first.';
    } else if (pendingVP > 0) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Forward to HR (SF Office)';
      btn.title = pendingVP + ' candidate(s) still pending review at VP. Complete all reviews first.';
    } else {
      btn.disabled = false;
      btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Forward to HR (SF Office)';
      btn.title = 'Forward all scrutinised candidates of ' + d.department + ' to HR';
    }
  }

  async function forwardCurrentDeptToHR() {
    var dept = document.getElementById('filter-dept').value;
    if (!dept) {
      toast('Please select a specific department first', 'error');
      return;
    }
    if (!confirm('Forward all scrutinised candidates of "' + dept + '" to HR (SF Office)? Once forwarded, candidate reviews for this department will be locked.')) return;

    try {
      var res = await api('/api/vp/forward-hr', {
        method: 'POST',
        body: JSON.stringify({ department: dept })
      });
      var data = await res.json();
      if (res.ok) {
        toast('Department "' + dept + '" successfully forwarded to HR!', 'success');
        await loadDepartments();
        updateDeptActionBar();
        loadApps();
      } else {
        toast(data.error || 'Forwarding failed', 'error');
      }
    } catch(e) {
      toast('Error: ' + e, 'error');
    }
  }

  async function loadApps() {
    var wrap = document.getElementById('table-wrap');
    var q = document.getElementById('search-input').value;
    var dept = document.getElementById('filter-dept').value;
    var hod = document.getElementById('filter-hod').value;
    var vp = document.getElementById('filter-vp').value;

    if (dept && deptForwardedMap[dept] && !deptForwardedMap[dept].is_hod_forwarded && !deptForwardedMap[dept].is_forwarded) {
      wrap.innerHTML = '<div class="empty-state"><i class="fa-solid fa-clock-rotate-left" style="color:#d97706; font-size: 2.5rem; margin-bottom: .75rem;"></i>' +
        '<h3 style="font-weight:700; color:#1e293b; margin-bottom:.5rem;">Department Scrutiny Pending Forwarding</h3>' +
        '<p style="max-width:520px; margin:0 auto; line-height:1.5;">The HOD for <strong>' + esc(dept) + '</strong> has not forwarded scrutinised candidates to the Vice Principal yet. Eligible candidates from this department will appear here once HOD forwarding is complete.</p></div>';
      document.getElementById('count-label').textContent = '(0)';
      document.getElementById('s-total').textContent = '0';
      document.getElementById('s-eligible').textContent = '0';
      document.getElementById('s-shortlisted').textContent = '0';
      document.getElementById('s-today').textContent = '0';
      return;
    }

    var url = '/api/applications?';
    if (q) url += 'q=' + encodeURIComponent(q) + '&';
    if (dept) url += 'department=' + encodeURIComponent(dept) + '&';
    if (hod) url += 'hod_status=' + encodeURIComponent(hod) + '&';
    if (vp) url += 'vp_status=' + encodeURIComponent(vp) + '&';

    try {
      var res = await api(url);
      var data = await res.json();
      var apps = data.applications || [];

      document.getElementById('count-label').textContent = '(' + apps.length + ')';
      document.getElementById('s-total').textContent = apps.length;
      document.getElementById('s-eligible').textContent = apps.filter(function(a){return a.hod_status==='Eligible'}).length;
      document.getElementById('s-shortlisted').textContent = apps.filter(function(a){return a.vp_status==='Shortlisted'}).length;
      var today = new Date().toISOString().split('T')[0];
      document.getElementById('s-today').textContent = apps.filter(function(a){return (a.submitted_at||'').startsWith(today)}).length;

      if (!apps.length) {
        wrap.innerHTML = '<div class="empty-state"><i class="fa-solid fa-inbox"></i>No eligible forwarded candidates available.</div>';
        return;
      }

      var html = '<table><thead><tr><th>#</th><th>Name</th><th>Position</th><th>Department</th><th>Email</th><th>Date</th><th>HOD</th><th>VP</th><th>Actions</th></tr></thead><tbody>';
      apps.forEach(function(a, i) {
        var hodSc = {'Pending':'s-pending','Eligible':'s-eligible','Not Eligible':'s-not-eligible'}[a.hod_status] || 's-pending';
        var vpSc = {'Pending':'s-pending','Shortlisted':'s-shortlisted','Not Shortlisted':'s-not-shortlisted'}[a.vp_status] || 's-pending';
        var date = a.submitted_at ? new Date(a.submitted_at).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'}) : '—';
        
        var isDeptVpForwarded = a.vp_forwarded_at !== null && a.vp_forwarded_at !== undefined;
        var canShortlist = a.hod_status === 'Eligible' && a.vp_status === 'Pending' && !isDeptVpForwarded;

        html += '<tr><td>' + (i+1) + '</td>';
        html += '<td style="font-weight:600;">' + esc(a.name||'—') + '</td>';
        html += '<td>' + esc(a.position||'—') + '</td>';
        html += '<td>' + esc(a.department||'—') + '</td>';
        html += '<td>' + esc(a.email||'—') + '</td>';
        html += '<td>' + date + '</td>';
        html += '<td><span class="status-badge ' + hodSc + '">' + esc(a.hod_status||'Pending') + '</span></td>';
        html += '<td><span class="status-badge ' + vpSc + '">' + esc(a.vp_status||'Pending') + '</span></td>';
        html += '<td><div class="act-btns">';
        html += '<button class="btn-view" onclick="viewApp(' + a.id + ')">View</button>';
        if (canShortlist) {
          html += '<button class="btn-shortlist" onclick="vpReview(' + a.id + ',\'Shortlisted\')">✓ Shortlist</button>';
          html += '<button class="btn-reject" onclick="vpReview(' + a.id + ',\'Not Shortlisted\')">✗ Reject</button>';
        } else if (isDeptVpForwarded) {
          html += '<span style="font-size:.7rem; color:#059669; font-weight:600;">Locked (Forwarded to HR)</span>';
        } else if (a.hod_status !== 'Eligible') {
          html += '<button class="btn-shortlist btn-disabled" disabled title="HOD must mark as Eligible and forward department first">✓ Shortlist</button>';
        }
        html += '</div></td></tr>';
      });
      html += '</tbody></table>';
      wrap.innerHTML = html;
    } catch(e) { console.error(e); }
  }

  async function vpReview(id, status) {
    var remarks = '';
    if (status === 'Not Shortlisted') {
      remarks = prompt('Enter mandatory reason for marking as Not Shortlisted:');
      if (remarks === null) return;
      remarks = remarks.trim();
      if (!remarks) {
        toast('Reason is mandatory when marking a candidate as Not Shortlisted', 'error');
        return;
      }
    } else {
      if (!confirm('Shortlist this candidate?')) return;
    }

    try {
      var res = await api('/api/applications/' + id + '/vp-review', {
        method: 'PUT',
        body: JSON.stringify({ vp_status: status, vp_remarks: remarks })
      });
      var data = await res.json();
      if (res.ok) {
        toast('Candidate marked as ' + status, 'success');
        await loadDepartments();
        updateDeptActionBar();
        loadApps();
      } else {
        toast(data.error || 'Failed', 'error');
      }
    } catch(e) { toast('Error: ' + e, 'error'); }
  }

  async function viewApp(id) {
    try {
      var res = await api('/api/applications/' + id);
      if (!res.ok) { toast('Failed to load details', 'error'); return; }
      var app = await res.json();

      var rRes = await api('/api/applications/' + id + '/research');
      var rData = rRes.ok ? await rRes.json() : { counts: {}, publications: [], patents: [], consultancy: [], projects: [] };
      var c = rData.counts || {};

      document.getElementById('modal-title').textContent = (app.name||'Applicant') + ' — ' + (app.position||'') + ' (' + (app.department||'') + ')';

      var html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:.75rem; padding:1rem; margin-bottom:1.25rem;">';
      html += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:.75rem;">';
      html += '<h4 style="font-size:.9rem; font-weight:700; color:#002e5b;">📊 Research Summary Counts</h4>';
      html += '<button onclick="downloadPdf(' + id + ')" style="background:#002e5b; color:#fff; padding:.35rem .85rem; border-radius:.375rem; border:none; font-weight:600; font-size:.75rem; cursor:pointer;">📥 Download PDF</button>';
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
        'Application': ['position','department','app_uuid'],
        'Personal': ['name','dob','gender','email','mobile_no','father_name','category','community'],
        'Status': ['hod_status','vp_status','vp_remarks','admin_notes']
      };

      for (var sec in sections) {
        html += '<div class="dsec-title">' + sec + '</div><div class="dfgrid">';
        sections[sec].forEach(function(k) {
          var val = app[k] !== undefined && app[k] !== null ? String(app[k]) : '—';
          html += '<div class="dfield"><label>' + k.replace(/_/g,' ') + '</label><div class="val">' + esc(val) + '</div></div>';
        });
        html += '</div>';
      }

      // Structured Publications
      html += '<div class="dsec-title">Publications (' + (rData.publications||[]).length + ')</div>';
      if ((rData.publications||[]).length) {
        html += '<table style="margin-bottom:.75rem;"><thead><tr><th>Type</th><th>Indexing</th><th>Title</th><th>Publisher/Journal</th><th>Year</th></tr></thead><tbody>';
        rData.publications.forEach(function(p) {
          html += '<tr><td>' + esc(p.type||'—') + '</td><td>' + esc(p.indexing_category||p.scope||'—') + '</td><td style="font-weight:600;">' + esc(p.title||'—') + '</td><td>' + esc(p.publisher_journal||'—') + '</td><td>' + esc(p.year||'—') + '</td></tr>';
        });
        html += '</tbody></table>';
      } else { html += '<p style="font-size:.8rem;color:#94a3b8;margin-bottom:.75rem;">No publications listed.</p>'; }

      // Structured Patents & Projects
      html += '<div class="dsec-title">Patents & Projects</div>';
      html += '<div class="dfgrid">';
      html += '<div class="dfield"><label>Patents (' + (rData.patents||[]).length + ')</label><div class="val">' + ((rData.patents||[]).map(function(pt){return esc(pt.title)+' ['+esc(pt.status)+']';}).join('<br/>') || 'None') + '</div></div>';
      html += '<div class="dfield"><label>Projects (' + (rData.projects||[]).length + ')</label><div class="val">' + ((rData.projects||[]).map(function(pr){return esc(pr.title)+' ['+esc(pr.type)+' Project, Role: '+esc(pr.role||'PI')+']';}).join('<br/>') || 'None') + '</div></div>';
      html += '</div>';

      if (app.resume_path) html += '<div class="dsec-title">Files</div><a href="' + app.resume_path + '" target="_blank" class="file-link">📄 View Resume</a>';
      document.getElementById('modal-body').innerHTML = html;
      document.getElementById('detail-overlay').classList.add('active');
    } catch(e) { toast('Error loading details', 'error'); }
  }

  async function downloadPdf(id) {
    try {
      var res = await fetch('/api/applications/' + id + '/pdf', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!res.ok) { toast('PDF generation failed', 'error'); return; }
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    } catch(e) { toast('Error downloading PDF', 'error'); }
  }

  async function downloadReport(reportType) {
    var dept = document.getElementById('filter-dept').value;
    var endpointMap = {
      'shortlisted-pdf': '/api/reports/vp-shortlisted-pdf',
      'not-shortlisted-pdf': '/api/reports/vp-not-shortlisted-pdf',
      'shortlisted-csv': '/api/reports/vp-shortlisted-csv',
      'not-shortlisted-csv': '/api/reports/vp-not-shortlisted-csv'
    };
    var base = endpointMap[reportType];
    if (!base) return;
    var url = base + '?department=' + encodeURIComponent(dept);

    try {
      var res = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
      if (!res.ok) {
        var errJson = await res.json().catch(function(){ return {}; });
        toast(errJson.error || 'Failed to download report', 'error');
        return;
      }
      var blob = await res.blob();
      var blobUrl = URL.createObjectURL(blob);
      var ext = reportType.indexOf('csv') !== -1 ? 'csv' : 'pdf';
      var filename = 'VP_' + reportType.replace('-','_') + '.' + ext;
      var a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(blobUrl);
    } catch(e) {
      toast('Report download error: ' + e, 'error');
    }
  }

  ['modal-close','modal-cancel'].forEach(function(id) {
    document.getElementById(id).addEventListener('click', function() { document.getElementById('detail-overlay').classList.remove('active'); });
  });
  document.getElementById('detail-overlay').addEventListener('click', function(e) { if(e.target===e.currentTarget) e.currentTarget.classList.remove('active'); });

  loadDepartments().then(function() {
    updateDeptActionBar();
    loadApps();
  });
