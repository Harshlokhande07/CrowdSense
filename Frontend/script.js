// CrowdSense Control Room Dashboard Client Integration Script

(function() {
  'use strict';

  // DOM Elements
  const tabs = Array.from(document.querySelectorAll('.nv'));
  const sections = Array.from(document.querySelectorAll('.main-tab'));
  const connBanner = document.getElementById('connection-banner');

  const chipDemoBadge = document.getElementById('chip-demo-badge');
  const chipSource = document.getElementById('chip-source');
  const chipCamera = document.getElementById('chip-camera');
  const chipModel = document.getElementById('chip-model');
  const chipDb = document.getElementById('chip-db');
  const chipFps = document.getElementById('chip-fps');
  const riskBadge = document.getElementById('overall-risk-badge');

  const btnSrcDemo = document.getElementById('btn-src-demo');
  const btnSrcWebcam = document.getElementById('btn-src-webcam');
  const btnSrcUpload = document.getElementById('btn-src-upload');
  const videoFileInput = document.getElementById('video-file-input');
  const sourceUploadError = document.getElementById('source-upload-error');

  const kpiPeople = document.getElementById('kpi-people');
  const kpiAvgDensity = document.getElementById('kpi-avg-density');
  const kpiMaxDensity = document.getElementById('kpi-max-density');
  const kpiActiveAlerts = document.getElementById('kpi-active-alerts');
  const kpiRiskScore = document.getElementById('kpi-risk-score');

  const gridMatrix = document.getElementById('grid-matrix');
  const gridMatrixLarge = document.getElementById('grid-matrix-large');
  const zoneDetailedBreakdown = document.getElementById('zone-detailed-breakdown');
  const bottleneckList = document.getElementById('bottleneck-list');
  const zoneRankingList = document.getElementById('zone-ranking-list');
  const activeIncidentsList = document.getElementById('active-incidents-list');
  const alertsHistoryList = document.getElementById('alerts-history-list');
  const healthTableBody = document.getElementById('health-table-body');
  
  const trendSvg = document.getElementById('trend-chart-svg');
  const trendLegend = document.getElementById('trend-legend-container');
  const trendDetails = document.getElementById('trend-details-container');

  // Input Video Source Selection Handlers
  function updateSourceUI(src) {
    if (!src) return;
    const mode = src.mode || 'demo';
    const name = src.display_name || 'SIMULATION';

    if (chipSource) {
      if (mode === 'video') {
        chipSource.textContent = `Source: Uploaded video (${name})`;
      } else if (mode === 'webcam') {
        chipSource.textContent = `Source: Live Webcam`;
      } else {
        chipSource.textContent = `Source: Demo Mode`;
      }
    }

    if (chipDemoBadge) {
      chipDemoBadge.classList.toggle('hidden', mode !== 'demo');
    }

    if (btnSrcDemo) btnSrcDemo.classList.toggle('active', mode === 'demo');
    if (btnSrcWebcam) btnSrcWebcam.classList.toggle('active', mode === 'webcam');
    if (btnSrcUpload) btnSrcUpload.classList.toggle('active', mode === 'video');
  }

  function selectSourceMode(mode) {
    if (sourceUploadError) sourceUploadError.classList.add('hidden');
    fetch('/api/source/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode })
    })
    .then(res => res.json())
    .then(resData => {
      if (resData.source) {
        updateSourceUI(resData.source);
      }
    })
    .catch(err => {
      console.error('[CrowdSense] Error selecting source mode:', err);
    });
  }

  if (btnSrcDemo) {
    btnSrcDemo.addEventListener('click', () => selectSourceMode('demo'));
  }

  if (btnSrcWebcam) {
    btnSrcWebcam.addEventListener('click', () => selectSourceMode('webcam'));
  }

  if (videoFileInput) {
    videoFileInput.addEventListener('change', () => {
      const file = videoFileInput.files[0];
      if (!file) return;

      if (sourceUploadError) sourceUploadError.classList.add('hidden');

      const formData = new FormData();
      formData.append('file', file);

      fetch('/api/source/upload', {
        method: 'POST',
        body: formData
      })
      .then(res => {
        if (!res.ok) {
          return res.json().then(errData => {
            throw new Error(errData.detail || 'File upload failed.');
          });
        }
        return res.json();
      })
      .then(resData => {
        if (resData.source) {
          updateSourceUI(resData.source);
        }
        videoFileInput.value = '';
      })
      .catch(err => {
        if (sourceUploadError) {
          sourceUploadError.textContent = `⚠️ ${err.message}`;
          sourceUploadError.classList.remove('hidden');
        }
        videoFileInput.value = '';
      });
    });
  }

  // Tab Navigation Handling
  function switchTab(index) {
    sections.forEach((sec, i) => {
      sec.style.display = (i === index) ? 'flex' : 'none';
      if (i === index) sec.style.flexDirection = 'column';
    });
    tabs.forEach((tab, i) => {
      tab.classList.toggle('on', i === index);
    });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', (e) => {
      e.preventDefault();
      history.replaceState(null, '', '#t' + index);
      switchTab(index);
    });
  });

  const initialTab = Math.max(0, parseInt((location.hash || '#t0').slice(2)) || 0);
  switchTab(initialTab);

  // WebSocket Connection Handling
  let socket = null;
  let reconnectInterval = 1000;
  const maxReconnectInterval = 10000;

  function setBackendOfflineState() {
    if (connBanner) {
      connBanner.textContent = '⚠️ LIVE CONNECTION LOST — BACKEND OFFLINE (Reconnecting...)';
      connBanner.classList.remove('hidden');
    }
  }

  function connectWebSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = function() {
      console.log('[CrowdSense] WebSocket connection established.');
      if (connBanner) connBanner.classList.add('hidden');
      reconnectInterval = 1000;
    };

    socket.onmessage = function(event) {
      try {
        const data = JSON.parse(event.data);
        updateDashboardUI(data);
      } catch (err) {
        console.error('[CrowdSense] Error parsing WebSocket JSON payload:', err);
      }
    };

    socket.onclose = function() {
      console.warn('[CrowdSense] WebSocket connection closed.');
      setBackendOfflineState();
      socket = null;
      setTimeout(connectWebSocket, reconnectInterval);
      reconnectInterval = Math.min(reconnectInterval * 1.5, maxReconnectInterval);
    };

    socket.onerror = function(err) {
      console.error('[CrowdSense] WebSocket error:', err);
      socket.close();
    };
  }

  // Fallback Polling if WebSocket is disconnected
  setInterval(function() {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      fetch('/api/state')
        .then(res => res.json())
        .then(data => {
          if (connBanner) connBanner.classList.add('hidden');
          updateDashboardUI(data);
        })
        .catch(() => {
          setBackendOfflineState();
        });
    }
  }, 2000);

  // Core Dashboard UI Update Function (uses textContent strictly)
  function updateDashboardUI(data) {
    if (!data) return;

    const sys = data.system || {};
    const src = data.source || sys.source || {};
    updateSourceUI(src);
    
    // 1. Status Chips with Explicit States
    const camStatus = sys.demo_mode ? 'DEMO MODE' : (sys.camera || 'CAMERA OFFLINE');
    const modelStatus = sys.model || 'AI MODEL UNAVAILABLE';
    const dbStatus = sys.database || 'DATABASE DISCONNECTED';
    
    const procFps = src.processing_fps !== undefined ? src.processing_fps.toFixed(1) : (sys.fps !== undefined ? sys.fps.toFixed(1) : '--');
    const vidFps = src.video_fps !== undefined ? src.video_fps.toFixed(1) : '--';
    const dropped = src.dropped_frames || 0;

    if (chipDemoBadge) {
      chipDemoBadge.classList.toggle('hidden', !(sys.demo_thresholds || sys.demo_mode || src.mode === 'demo'));
    }

    if (chipCamera) chipCamera.textContent = `Camera: ${camStatus}`;
    if (chipModel) chipModel.textContent = `AI Model: ${modelStatus}`;
    if (chipDb) chipDb.textContent = `Database: ${dbStatus}`;
    if (chipFps) {
      if (src.mode === 'video') {
        chipFps.textContent = `Proc FPS: ${procFps} / Video FPS: ${vidFps} (Dropped: ${dropped})`;
      } else {
        chipFps.textContent = `FPS: ${procFps}`;
      }
    }

    // 2. Overall Risk Badge
    const risk = data.risk || {};
    const riskLevel = risk.level || 'NORMAL';
    if (riskBadge) {
      riskBadge.textContent = `STATUS: ${riskLevel}`;
      riskBadge.className = 'risk-badge ' + (
        riskLevel === 'CRITICAL' ? 'badge-critical' :
        riskLevel === 'HIGH' ? 'badge-high' :
        riskLevel === 'WARNING' ? 'badge-warning' : 'badge-normal'
      );
    }

    // 3. KPI Numbers & 0 People Detected Badge
    const pCount = data.people_count !== undefined ? data.people_count : 0;
    if (kpiPeople) {
      kpiPeople.textContent = pCount === 0 ? '0 PEOPLE DETECTED' : String(pCount);
    }

    if (kpiAvgDensity) {
      kpiAvgDensity.textContent = data.density && data.density.avg !== undefined ? data.density.avg.toFixed(2) : '0.00';
    }

    if (kpiMaxDensity) {
      kpiMaxDensity.textContent = data.density && data.density.max !== undefined ? String(data.density.max) : '0';
    }

    const activeAlerts = data.alerts_active || [];
    if (kpiActiveAlerts) kpiActiveAlerts.textContent = String(activeAlerts.length);
    if (kpiRiskScore) kpiRiskScore.textContent = `Max Risk Score: ${risk.score || 0}/100`;

    // 4. Render 8x8 Grid Matrix (Tab #t0 & Tab #t1)
    const gridData = data.grid || [];
    renderGridMatrix(gridMatrix, gridData);
    renderGridMatrix(gridMatrixLarge, gridData);

    // 5. Zone Detailed Sector Breakdown (Tab #t1)
    renderZoneBreakdown(zoneDetailedBreakdown, data.zones || []);

    // 6. Bottleneck Panel & Zone Rankings
    renderBottlenecks(bottleneckList, data.bottlenecks || []);
    renderZoneRankings(zoneRankingList, data.zones || []);

    // 6b. Venue Floor Plan SVG Map
    const floorPlanEl = document.getElementById('venue-floorplan-svg');
    if (floorPlanEl) {
      renderFloorPlan(floorPlanEl, data.zones || []);
    }

    // 7. Active Incidents & History
    renderActiveIncidents(activeIncidentsList, activeAlerts);
    renderAlertsHistory(alertsHistoryList, data.alerts_history || []);

    // 8. Health Telemetry Table (Tab #t4)
    renderHealthTable(healthTableBody, sys, data.notifications || {});

    // 9. Trend Chart SVG (Tab #t2)
    renderTrendSVG(trendSvg, trendLegend, trendDetails, data);
  }

  // Render Venue Floor Plan SVG
  function renderFloorPlan(svg, zones) {
    if (!svg) return;
    clearElement(svg);

    const ns = 'http://www.w3.org/2000/svg';
    const zoneMap = {};
    zones.forEach(z => { zoneMap[z.id] = z; });

    const sectorDefs = [
      { id: 'ZONE_A', name: 'Gate 3 Entry (NW)', x: 10, y: 10, w: 135, h: 85 },
      { id: 'ZONE_B', name: 'Main Concourse (NE)', x: 155, y: 10, w: 135, h: 85 },
      { id: 'ZONE_C', name: 'East Lane Merge (SW)', x: 10, y: 105, w: 135, h: 85 },
      { id: 'ZONE_D', name: 'West Exit Area (SE)', x: 155, y: 105, w: 135, h: 85 }
    ];

    const getLvlColor = (lvl) => {
      if (lvl === 'CRITICAL') return { fill: '#7F1D1D', stroke: '#EF4444' };
      if (lvl === 'HIGH') return { fill: '#7C2D12', stroke: '#F97316' };
      if (lvl === 'WARNING' || lvl === 'ELEVATED') return { fill: '#78350F', stroke: '#F59E0B' };
      return { fill: '#064E3B', stroke: '#10B981' };
    };

    sectorDefs.forEach(sec => {
      const zData = zoneMap[sec.id] || {};
      const lvl = zData.level || 'NORMAL';
      const colors = getLvlColor(lvl);

      const rect = document.createElementNS(ns, 'rect');
      rect.setAttribute('x', sec.x);
      rect.setAttribute('y', sec.y);
      rect.setAttribute('width', sec.w);
      rect.setAttribute('height', sec.h);
      rect.setAttribute('rx', '6');
      rect.setAttribute('fill', colors.fill);
      rect.setAttribute('stroke', colors.stroke);
      rect.setAttribute('stroke-width', '2');
      rect.setAttribute('opacity', '0.9');
      svg.appendChild(rect);

      const title = document.createElementNS(ns, 'text');
      title.setAttribute('x', sec.x + 10);
      title.setAttribute('y', sec.y + 22);
      title.setAttribute('fill', '#FFFFFF');
      title.setAttribute('font-size', '11');
      title.setAttribute('font-weight', '700');
      title.textContent = zData.name || sec.name;
      svg.appendChild(title);

      const countText = document.createElementNS(ns, 'text');
      countText.setAttribute('x', sec.x + 10);
      countText.setAttribute('y', sec.y + 44);
      countText.setAttribute('fill', '#E2E8F0');
      countText.setAttribute('font-size', '13');
      countText.setAttribute('font-weight', '800');
      const pM2 = zData.density_per_m2 !== undefined ? `${zData.density_per_m2} p/m²` : '';
      countText.textContent = `${zData.count || 0} people ${pM2 ? '· ' + pM2 : ''}`;
      svg.appendChild(countText);

      const badgeText = document.createElementNS(ns, 'text');
      badgeText.setAttribute('x', sec.x + 10);
      badgeText.setAttribute('y', sec.y + 68);
      badgeText.setAttribute('fill', colors.stroke);
      badgeText.setAttribute('font-size', '11');
      badgeText.setAttribute('font-weight', '700');
      badgeText.textContent = `● ${lvl} (${zData.movement || 'FLOW'})`;
      svg.appendChild(badgeText);
    });
  }

  // Helper to safely clear container
  function clearElement(el) {
    if (!el) return;
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }

  // Render 8x8 Grid Cells
  function renderGridMatrix(container, gridData) {
    if (!container) return;
    clearElement(container);

    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const cell = document.createElement('div');
        const count = (gridData[r] && gridData[r][c] !== undefined) ? gridData[r][c] : 0;

        let levelClass = 'cell-normal';
        if (count >= 7) levelClass = 'cell-critical';
        else if (count >= 5) levelClass = 'cell-high';
        else if (count >= 3) levelClass = 'cell-elevated';

        cell.className = `grid-cell ${levelClass}`;
        cell.textContent = count > 0 ? String(count) : '';
        cell.title = `Grid Cell [Row ${r+1}, Col ${c+1}]: ${count} people`;
        container.appendChild(cell);
      }
    }
  }

  // Render Zone Detailed Breakdown Panel (Tab #t1)
  function renderZoneBreakdown(container, zones) {
    if (!container) return;
    clearElement(container);

    if (!zones || zones.length === 0) {
      const ph = document.createElement('div');
      ph.style.color = '#94A3B8';
      ph.style.fontSize = '14px';
      ph.textContent = 'No zone breakdown data available.';
      container.appendChild(ph);
      return;
    }

    zones.forEach(z => {
      const card = document.createElement('div');
      card.className = 'breakdown-card';

      const header = document.createElement('div');
      header.className = 'breakdown-header';

      const name = document.createElement('div');
      name.className = 'breakdown-name';
      name.textContent = z.name || z.id;

      const badge = document.createElement('span');
      badge.className = 'breakdown-badge';
      const lvl = z.level || 'NORMAL';
      badge.textContent = lvl;
      badge.style.backgroundColor = (lvl === 'CRITICAL') ? '#EF4444' : (lvl === 'HIGH') ? '#F97316' : (lvl === 'ELEVATED') ? '#F59E0B' : '#10B981';
      badge.style.color = (lvl === 'ELEVATED') ? '#000000' : '#FFFFFF';

      header.appendChild(name);
      header.appendChild(badge);

      const info = document.createElement('div');
      info.className = 'breakdown-info';
      info.textContent = `Count: ${z.count || 0} people | Risk Score: ${z.risk_score || 0}/100`;

      card.appendChild(header);
      card.appendChild(info);

      if (z.reasons && z.reasons.length > 0) {
        const reasons = document.createElement('div');
        reasons.className = 'breakdown-reasons';
        reasons.textContent = `Reasons: ${z.reasons.join(', ')}`;
        card.appendChild(reasons);
      }

      container.appendChild(card);
    });
  }

  // Render Bottlenecks using textContent nodes
  function renderBottlenecks(container, bottlenecks) {
    if (!container) return;
    clearElement(container);

    if (bottlenecks.length === 0) {
      const placeholder = document.createElement('div');
      placeholder.className = 'placeholder-text';
      placeholder.style.color = '#94A3B8';
      placeholder.style.fontSize = '14px';
      placeholder.textContent = 'No congestion bottlenecks detected. Crowd flow clear.';
      container.appendChild(placeholder);
      return;
    }

    bottlenecks.forEach(b => {
      const item = document.createElement('div');
      item.className = 'bottleneck-item';

      const title = document.createElement('div');
      title.className = 'bn-title';
      title.textContent = `🚨 ${b.zone_name || b.zone_id} — Score ${b.score}/100`;

      const sub = document.createElement('div');
      sub.className = 'bn-reasons';
      sub.textContent = `State: ${b.state} (Persisting for ${b.persistence_duration_s || 0}s)`;

      const reasons = document.createElement('div');
      reasons.className = 'bn-reasons';
      reasons.textContent = `Reasons: ${(b.reasons || []).join(', ')}`;

      item.appendChild(title);
      item.appendChild(sub);
      item.appendChild(reasons);
      container.appendChild(item);
    });
  }

  // Render Zone Rankings
  function renderZoneRankings(container, zones) {
    if (!container) return;
    clearElement(container);

    if (zones.length === 0) {
      const ph = document.createElement('div');
      ph.textContent = 'No zone data available.';
      ph.style.color = '#94A3B8';
      container.appendChild(ph);
      return;
    }

    const sortedZones = [...zones].sort((a, b) => (b.count || 0) - (a.count || 0));

    sortedZones.forEach(z => {
      const item = document.createElement('div');
      item.className = 'zone-item';

      const left = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'zone-name';
      name.textContent = z.name || z.id;

      const details = document.createElement('small');
      details.style.color = '#94A3B8';
      details.style.fontSize = '12px';
      details.textContent = `Move: ${z.movement || 'STAGNANT'} | Risk: ${z.risk_score || 0}%`;

      left.appendChild(name);
      left.appendChild(details);

      const right = document.createElement('div');
      right.className = 'zone-val';
      right.style.color = (z.level === 'CRITICAL') ? '#EF4444' : (z.level === 'HIGH') ? '#F97316' : '#10B981';
      right.textContent = `${z.count || 0} p`;

      item.appendChild(left);
      item.appendChild(right);
      container.appendChild(item);
    });
  }

  // Render Active Incidents (Tab #t3)
  function renderActiveIncidents(container, incidents) {
    if (!container) return;
    clearElement(container);

    if (!incidents || incidents.length === 0) {
      const okMsg = document.createElement('div');
      okMsg.style.color = '#10B981';
      okMsg.style.fontWeight = '700';
      okMsg.style.padding = '12px';
      okMsg.textContent = '✅ No active incident alerts.';
      container.appendChild(okMsg);
      return;
    }

    incidents.forEach(inc => {
      const card = document.createElement('div');
      card.className = 'incident-card';
      card.style.background = '#151C2C';
      card.style.borderLeft = (inc.status === 'ACKNOWLEDGED') ? '4px solid #F59E0B' : '4px solid #EF4444';
      card.style.padding = '14px';
      card.style.borderRadius = '8px';
      card.style.marginBottom = '12px';

      // Header: Severity & Zone Name + Status Badge
      const headerRow = document.createElement('div');
      headerRow.style.display = 'flex';
      headerRow.style.justifyContent = 'space-between';
      headerRow.style.alignItems = 'center';

      const title = document.createElement('div');
      title.style.fontWeight = '800';
      title.style.fontSize = '16px';
      title.style.color = '#FFF';
      title.textContent = `${inc.severity || 'ALERT'} — ${inc.zone_name || inc.zone_id}`;

      const badge = document.createElement('span');
      const st = inc.status || 'ACTIVE';
      badge.textContent = st;
      badge.style.padding = '4px 10px';
      badge.style.borderRadius = '12px';
      badge.style.fontSize = '12px';
      badge.style.fontWeight = '800';
      badge.style.backgroundColor = (st === 'ACKNOWLEDGED') ? '#F59E0B' : (st === 'RESOLVED') ? '#10B981' : '#EF4444';
      badge.style.color = (st === 'ACKNOWLEDGED') ? '#000' : '#FFF';

      headerRow.appendChild(title);
      headerRow.appendChild(badge);
      card.appendChild(headerRow);

      // Metadata details
      const meta = document.createElement('div');
      meta.style.color = '#94A3B8';
      meta.style.fontSize = '13px';
      meta.style.margin = '6px 0';
      const createdLocal = inc.created_at ? new Date(inc.created_at).toLocaleString() : 'N/A';
      meta.textContent = `Count: ${inc.current_count} (Peak: ${inc.peak_count}) · Started: ${createdLocal} · Duration: ${inc.duration_s || 0}s`;
      card.appendChild(meta);

      // Acknowledged info line
      if (inc.status === 'ACKNOWLEDGED' && inc.ack_by) {
        const ackInfo = document.createElement('div');
        ackInfo.style.color = '#F59E0B';
        ackInfo.style.fontSize = '13px';
        ackInfo.style.margin = '4px 0';
        ackInfo.style.fontWeight = '600';
        const ackLocal = inc.ack_at ? new Date(inc.ack_at).toLocaleString() : 'N/A';
        let ackText = `Acknowledged by ${inc.ack_by} at ${ackLocal}`;
        if (inc.note) {
          ackText += ` ("${inc.note}")`;
        }
        ackInfo.textContent = ackText;
        card.appendChild(ackInfo);
      }

      // Suggested action & Action Playbook
      const actionBox = document.createElement('div');
      actionBox.style.marginTop = '8px';
      actionBox.style.padding = '8px 12px';
      actionBox.style.background = '#0F172A';
      actionBox.style.borderRadius = '6px';
      actionBox.style.border = '1px solid #1E293B';

      const actionTitle = document.createElement('div');
      actionTitle.style.color = '#38BDF8';
      actionTitle.style.fontWeight = '700';
      actionTitle.style.fontSize = '13px';
      actionTitle.textContent = '⚡ Recommended Operator Playbook (Human Verification Required):';
      actionBox.appendChild(actionTitle);

      if (inc.recommended_actions && inc.recommended_actions.length > 0) {
        const actionList = document.createElement('ul');
        actionList.style.margin = '4px 0 0 16px';
        actionList.style.padding = '0';
        actionList.style.fontSize = '12px';
        actionList.style.color = '#E2E8F0';
        inc.recommended_actions.forEach(act => {
          const li = document.createElement('li');
          li.style.marginTop = '2px';
          li.textContent = act;
          actionList.appendChild(li);
        });
        actionBox.appendChild(actionList);
      } else {
        const actionText = document.createElement('div');
        actionText.style.color = '#E2E8F0';
        actionText.style.fontSize = '12px';
        actionText.style.marginTop = '2px';
        actionText.textContent = inc.action_recommended || 'Maintain continuous visual monitoring.';
        actionBox.appendChild(actionText);
      }
      card.appendChild(actionBox);

      // Operator action controls
      const formBox = document.createElement('div');
      formBox.style.marginTop = '12px';
      formBox.style.display = 'flex';
      formBox.style.flexDirection = 'column';
      formBox.style.gap = '8px';

      const inputRow = document.createElement('div');
      inputRow.style.display = 'flex';
      inputRow.style.gap = '8px';

      const opInput = document.createElement('input');
      opInput.type = 'text';
      opInput.placeholder = 'Operator name (max 40 chars)';
      opInput.maxLength = 40;
      opInput.style.flex = '1';
      opInput.style.padding = '6px 10px';
      opInput.style.borderRadius = '4px';
      opInput.style.border = '1px solid #334155';
      opInput.style.background = '#0F172A';
      opInput.style.color = '#FFF';
      if (inc.ack_by) opInput.value = inc.ack_by;

      const noteInput = document.createElement('input');
      noteInput.type = 'text';
      noteInput.placeholder = 'Note (max 200 chars)';
      noteInput.maxLength = 200;
      noteInput.style.flex = '2';
      noteInput.style.padding = '6px 10px';
      noteInput.style.borderRadius = '4px';
      noteInput.style.border = '1px solid #334155';
      noteInput.style.background = '#0F172A';
      noteInput.style.color = '#FFF';

      inputRow.appendChild(opInput);
      inputRow.appendChild(noteInput);

      const btnRow = document.createElement('div');
      btnRow.style.display = 'flex';
      btnRow.style.gap = '8px';

      const ackBtn = document.createElement('button');
      ackBtn.textContent = 'Acknowledge';
      ackBtn.style.padding = '6px 14px';
      ackBtn.style.borderRadius = '4px';
      ackBtn.style.border = 'none';
      ackBtn.style.background = '#F59E0B';
      ackBtn.style.color = '#000';
      ackBtn.style.fontWeight = '700';
      ackBtn.style.cursor = 'pointer';

      const resolveBtn = document.createElement('button');
      resolveBtn.textContent = 'Resolve';
      resolveBtn.style.padding = '6px 14px';
      resolveBtn.style.borderRadius = '4px';
      resolveBtn.style.border = 'none';
      resolveBtn.style.background = '#10B981';
      resolveBtn.style.color = '#FFF';
      resolveBtn.style.fontWeight = '700';
      resolveBtn.style.cursor = 'pointer';

      const errFeedback = document.createElement('div');
      errFeedback.style.color = '#EF4444';
      errFeedback.style.fontSize = '12px';
      errFeedback.style.display = 'none';

      ackBtn.addEventListener('click', () => {
        errFeedback.style.display = 'none';
        const opVal = opInput.value.trim();
        const noteVal = noteInput.value.trim();
        if (!opVal) {
          errFeedback.textContent = 'Operator name is required to acknowledge.';
          errFeedback.style.display = 'block';
          return;
        }
        fetch(`/api/incidents/${inc.id}/ack`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ operator: opVal, note: noteVal })
        })
        .then(res => {
          if (!res.ok) return res.json().then(e => { throw new Error(e.detail || 'ACK failed'); });
          return res.json();
        })
        .then(() => {
          fetch('/api/state').then(r => r.json()).then(d => updateDashboardUI(d));
        })
        .catch(err => {
          errFeedback.textContent = err.message;
          errFeedback.style.display = 'block';
        });
      });

      resolveBtn.addEventListener('click', () => {
        errFeedback.style.display = 'none';
        const opVal = opInput.value.trim();
        const noteVal = noteInput.value.trim();
        fetch(`/api/incidents/${inc.id}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ operator: opVal || 'Operator', note: noteVal })
        })
        .then(res => {
          if (!res.ok) return res.json().then(e => { throw new Error(e.detail || 'Resolve failed'); });
          return res.json();
        })
        .then(() => {
          fetch('/api/state').then(r => r.json()).then(d => updateDashboardUI(d));
        })
        .catch(err => {
          errFeedback.textContent = err.message;
          errFeedback.style.display = 'block';
        });
      });

      btnRow.appendChild(ackBtn);
      btnRow.appendChild(resolveBtn);

      formBox.appendChild(inputRow);
      formBox.appendChild(btnRow);
      formBox.appendChild(errFeedback);
      card.appendChild(formBox);

      container.appendChild(card);
    });
  }

  // Render Alert History (Tab #t3)
  function renderAlertsHistory(container, history) {
    if (!container) return;
    clearElement(container);

    if (!history || history.length === 0) {
      const ph = document.createElement('div');
      ph.style.color = '#94A3B8';
      ph.style.fontSize = '13px';
      ph.style.padding = '10px';
      ph.textContent = 'No historical alerts logged yet.';
      container.appendChild(ph);
      return;
    }

    history.slice(0, 10).forEach(h => {
      const row = document.createElement('div');
      row.style.padding = '8px 0';
      row.style.borderBottom = '1px solid #334155';
      row.style.fontSize = '13px';

      const eventTimeRaw = (h.status === 'RESOLVED' && h.resolved_at) ? h.resolved_at : (h.created_at || h.last_seen || h.timestamp || '');
      const eventTimeLocal = eventTimeRaw ? new Date(eventTimeRaw).toLocaleString() : 'N/A';

      row.textContent = `[${eventTimeLocal}] ${h.status || 'RESOLVED'} — ${h.severity || 'ALERT'} ${h.zone_name || h.zone_id || 'Zone'} (${h.current_count || h.count || 0} people, Peak ${h.peak_count || h.current_count || 0})`;
      if (h.note) {
        row.textContent += ` — Note: "${h.note}"`;
      }
      container.appendChild(row);
    });
  }

  // Render System Telemetry Table (Tab #t4)
  function renderHealthTable(container, sys, notifications) {
    if (!container) return;
    clearElement(container);

    const rows = [
      { comp: 'Camera Feed', status: sys.demo_mode ? 'DEMO MODE' : (sys.camera || 'CAMERA OFFLINE'), detail: sys.demo_mode ? 'Running synthetic demo simulation' : 'Live video input' },
      { comp: 'YOLOv8 AI Model', status: sys.model || 'AI MODEL UNAVAILABLE', detail: 'Class 0 person detection & ByteTrack' },
      { comp: 'Firestore Database', status: notifications.database || 'DATABASE DISCONNECTED', detail: 'Incident log persistence' },
      { comp: 'Twilio SMS Gateway', status: notifications.twilio || 'NOT_CONFIGURED', detail: 'Critical SMS dispatch' },
      { comp: 'ntfy.sh Mobile Push', status: notifications.ntfy || 'READY', detail: 'Mobile alert channel' }
    ];

    rows.forEach(r => {
      const tr = document.createElement('tr');

      const tdComp = document.createElement('td');
      tdComp.style.padding = '12px 16px';
      tdComp.style.fontWeight = '700';
      tdComp.textContent = r.comp;

      const tdStatus = document.createElement('td');
      tdStatus.style.padding = '12px 16px';
      tdStatus.style.color = (r.status === 'ONLINE' || r.status === 'READY' || r.status === 'CONNECTED' || r.status === 'OK') ? '#10B981' : '#F59E0B';
      tdStatus.textContent = r.status;

      const tdDetail = document.createElement('td');
      tdDetail.style.padding = '12px 16px';
      tdDetail.style.color = '#94A3B8';
      tdDetail.style.fontSize = '13px';
      tdDetail.textContent = r.detail;

      tr.appendChild(tdComp);
      tr.appendChild(tdStatus);
      tr.appendChild(tdDetail);
      container.appendChild(tr);
    });

    renderAccuracyPanel();
  }

  // Render Detector Accuracy Panel (Tab #t4)
  function renderAccuracyPanel() {
    const panel = document.getElementById('accuracy-panel');
    if (!panel) return;

    fetch('/api/accuracy')
      .then(res => {
        if (res.status === 404) {
          clearElement(panel);
          const msg = document.createElement('div');
          msg.style.color = '#94A3B8';
          msg.style.fontSize = '14px';
          msg.textContent = 'No accuracy check run yet.';
          panel.appendChild(msg);
          return null;
        }
        if (!res.ok) throw new Error('Failed to load accuracy metrics');
        return res.json();
      })
      .then(data => {
        if (!data) return;
        clearElement(panel);

        const grid = document.createElement('div');
        grid.style.display = 'grid';
        grid.style.gridTemplateColumns = 'repeat(auto-fit, minmax(130px, 1fr))';
        grid.style.gap = '10px';

        const createMetricBox = (label, val, unit = '') => {
          const box = document.createElement('div');
          box.style.background = '#0F172A';
          box.style.padding = '10px 14px';
          box.style.borderRadius = '6px';
          box.style.border = '1px solid #334155';

          const lbl = document.createElement('div');
          lbl.style.color = '#94A3B8';
          lbl.style.fontSize = '12px';
          lbl.textContent = label;

          const v = document.createElement('div');
          v.style.color = '#FFF';
          v.style.fontSize = '18px';
          v.style.fontWeight = '800';
          v.textContent = `${val}${unit}`;

          box.appendChild(lbl);
          box.appendChild(v);
          return box;
        };

        const samplesCount = data.n_samples || 0;
        grid.appendChild(createMetricBox('Samples (Frames)', samplesCount));
        grid.appendChild(createMetricBox('MAE', data.mae !== undefined ? data.mae.toFixed(2) : '--', ' p'));
        grid.appendChild(createMetricBox('MAPE', data.mape !== undefined ? data.mape.toFixed(1) : '--', '%'));
        grid.appendChild(createMetricBox('Bias', data.bias !== undefined ? (data.bias > 0 ? `+${data.bias.toFixed(2)}` : data.bias.toFixed(2)) : '--'));

        const disclaimer = document.createElement('div');
        disclaimer.style.color = '#F59E0B';
        disclaimer.style.fontSize = '13px';
        disclaimer.style.fontWeight = '600';
        disclaimer.style.marginTop = '10px';
        disclaimer.textContent = `Measured on ${samplesCount} frames of 1 video. Not a general accuracy claim.`;

        panel.appendChild(grid);
        panel.appendChild(disclaimer);
      })
      .catch(() => {
        clearElement(panel);
        const msg = document.createElement('div');
        msg.style.color = '#94A3B8';
        msg.style.fontSize = '14px';
        msg.textContent = 'No accuracy check run yet.';
        panel.appendChild(msg);
      });
  }

  // Render Trend Forecast SVG Chart (Tab #t2)
  const zoneColors = ['#38BDF8', '#F59E0B', '#10B981', '#A855F7', '#EC4899', '#6366F1'];
  let zoneHistory = {};

  function renderTrendSVG(svg, legendEl, detailsEl, data) {
    if (!svg) return;
    clearElement(svg);
    if (legendEl) clearElement(legendEl);
    if (detailsEl) clearElement(detailsEl);

    const zones = data.zones || [];
    const now = Date.now();

    zones.forEach(z => {
      const zId = z.id || z.name;
      if (!zoneHistory[zId]) zoneHistory[zId] = [];
      zoneHistory[zId].push({ time: now, count: z.count || 0 });
      if (zoneHistory[zId].length > 20) zoneHistory[zId].shift();
    });

    const viewBoxW = 800;
    const viewBoxH = 320;
    const margin = { top: 30, right: 40, bottom: 50, left: 60 };
    const chartW = viewBoxW - margin.left - margin.right;
    const chartH = viewBoxH - margin.top - margin.bottom;

    svg.setAttribute('viewBox', `0 0 ${viewBoxW} ${viewBoxH}`);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.style.width = '100%';

    const ns = 'http://www.w3.org/2000/svg';

    let maxVal = 10;
    zones.forEach(z => {
      maxVal = Math.max(maxVal, z.count || 0);
      if (z.prediction && z.prediction.predicted_count !== undefined) {
        maxVal = Math.max(maxVal, z.prediction.predicted_count);
      }
    });
    maxVal = Math.ceil(maxVal * 1.25);

    const yTicks = 5;
    for (let i = 0; i <= yTicks; i++) {
      const val = Math.round((maxVal / yTicks) * i);
      const y = margin.top + chartH - (i / yTicks) * chartH;

      const line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', margin.left);
      line.setAttribute('y1', y);
      line.setAttribute('x2', margin.left + chartW);
      line.setAttribute('y2', y);
      line.setAttribute('stroke', '#334155');
      line.setAttribute('stroke-dasharray', '4 4');
      line.setAttribute('stroke-width', '1');
      svg.appendChild(line);

      const text = document.createElementNS(ns, 'text');
      text.setAttribute('x', margin.left - 10);
      text.setAttribute('y', y + 4);
      text.setAttribute('fill', '#94A3B8');
      text.setAttribute('font-size', '12');
      text.setAttribute('text-anchor', 'end');
      text.textContent = String(val);
      svg.appendChild(text);
    }

    const xLabels = [
      { text: '-45s', pct: 0.0 },
      { text: '-30s', pct: 0.2 },
      { text: '-15s', pct: 0.4 },
      { text: 'Now', pct: 0.6 },
      { text: '+15s', pct: 0.8 },
      { text: '+30s', pct: 1.0 }
    ];

    xLabels.forEach(lbl => {
      const x = margin.left + lbl.pct * chartW;

      const line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', x);
      line.setAttribute('y1', margin.top);
      line.setAttribute('x2', x);
      line.setAttribute('y2', margin.top + chartH);
      line.setAttribute('stroke', lbl.text === 'Now' ? '#38BDF8' : '#1E293B');
      line.setAttribute('stroke-width', lbl.text === 'Now' ? '1.5' : '1');
      if (lbl.text !== 'Now') line.setAttribute('stroke-dasharray', '2 2');
      svg.appendChild(line);

      const text = document.createElementNS(ns, 'text');
      text.setAttribute('x', x);
      text.setAttribute('y', margin.top + chartH + 20);
      text.setAttribute('fill', lbl.text === 'Now' ? '#38BDF8' : '#94A3B8');
      text.setAttribute('font-size', '12');
      text.setAttribute('font-weight', lbl.text === 'Now' ? '700' : '400');
      text.setAttribute('text-anchor', 'middle');
      text.textContent = lbl.text;
      svg.appendChild(text);
    });

    const xAxis = document.createElementNS(ns, 'line');
    xAxis.setAttribute('x1', margin.left);
    xAxis.setAttribute('y1', margin.top + chartH);
    xAxis.setAttribute('x2', margin.left + chartW);
    xAxis.setAttribute('y2', margin.top + chartH);
    xAxis.setAttribute('stroke', '#64748B');
    xAxis.setAttribute('stroke-width', '2');
    svg.appendChild(xAxis);

    const yAxis = document.createElementNS(ns, 'line');
    yAxis.setAttribute('x1', margin.left);
    yAxis.setAttribute('y1', margin.top);
    yAxis.setAttribute('x2', margin.left);
    yAxis.setAttribute('y2', margin.top + chartH);
    yAxis.setAttribute('stroke', '#64748B');
    yAxis.setAttribute('stroke-width', '2');
    svg.appendChild(yAxis);

    const xTitle = document.createElementNS(ns, 'text');
    xTitle.setAttribute('x', margin.left + chartW / 2);
    xTitle.setAttribute('y', viewBoxH - 10);
    xTitle.setAttribute('fill', '#F8FAFC');
    xTitle.setAttribute('font-size', '13');
    xTitle.setAttribute('font-weight', '700');
    xTitle.setAttribute('text-anchor', 'middle');
    xTitle.textContent = 'Time Horizon (seconds)';
    svg.appendChild(xTitle);

    const yTitle = document.createElementNS(ns, 'text');
    yTitle.setAttribute('x', -(margin.top + chartH / 2));
    yTitle.setAttribute('y', 18);
    yTitle.setAttribute('transform', 'rotate(-90)');
    yTitle.setAttribute('fill', '#F8FAFC');
    yTitle.setAttribute('font-size', '13');
    yTitle.setAttribute('font-weight', '700');
    yTitle.setAttribute('text-anchor', 'middle');
    yTitle.textContent = 'People Count (people)';
    svg.appendChild(yTitle);

    zones.forEach((z, idx) => {
      const zId = z.id || z.name;
      const color = zoneColors[idx % zoneColors.length];
      const history = zoneHistory[zId] || [];

      if (history.length > 0) {
        const points = [];
        const startX = margin.left;
        const nowX = margin.left + 0.6 * chartW;
        const totalHistTime = Math.max(1000, history[history.length - 1].time - history[0].time);

        history.forEach(pt => {
          const normT = (pt.time - history[0].time) / totalHistTime;
          const x = startX + normT * (nowX - startX);
          const y = margin.top + chartH - (pt.count / maxVal) * chartH;
          points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
        });

        if (points.length >= 2) {
          const path = document.createElementNS(ns, 'polyline');
          path.setAttribute('fill', 'none');
          path.setAttribute('stroke', color);
          path.setAttribute('stroke-width', '2.5');
          path.setAttribute('points', points.join(' '));
          svg.appendChild(path);
        }
      }

      const currentCount = z.count || 0;
      const predCount = z.prediction ? (z.prediction.predicted_count !== undefined ? z.prediction.predicted_count : currentCount) : currentCount;

      const nowX = margin.left + 0.6 * chartW;
      const nowY = margin.top + chartH - (currentCount / maxVal) * chartH;
      const predX = margin.left + 1.0 * chartW;
      const predY = margin.top + chartH - (predCount / maxVal) * chartH;

      const forecastPath = document.createElementNS(ns, 'line');
      forecastPath.setAttribute('x1', nowX);
      forecastPath.setAttribute('y1', nowY);
      forecastPath.setAttribute('x2', predX);
      forecastPath.setAttribute('y2', predY);
      forecastPath.setAttribute('stroke', color);
      forecastPath.setAttribute('stroke-width', '2.5');
      forecastPath.setAttribute('stroke-dasharray', '6 4');
      svg.appendChild(forecastPath);

      const dot = document.createElementNS(ns, 'circle');
      dot.setAttribute('cx', predX);
      dot.setAttribute('cy', predY);
      dot.setAttribute('r', '4');
      dot.setAttribute('fill', color);
      svg.appendChild(dot);

      const pred = z.prediction || {};
      const fcast = z.forecast || {};
      const isLowConf = pred.low_confidence || fcast.low_confidence || (pred.confidence_score !== undefined && pred.confidence_score < 0.3);
      const forecastMsg = fcast.message || pred.forecast_message || (fcast.time_to_threshold_sec ? `Reaches threshold in ~${fcast.time_to_threshold_sec}s` : null);

      if (legendEl) {
        const item = document.createElement('div');
        item.className = 'trend-legend-item';
        if (isLowConf) {
          item.style.opacity = '0.6';
        }

        const swatch = document.createElement('div');
        swatch.className = 'trend-legend-swatch';
        swatch.style.backgroundColor = isLowConf ? '#64748B' : color;

        const text = document.createElement('span');
        let legTxt = `${z.name || zId}: ${z.count || 0} → ${pred.predicted_count !== undefined ? pred.predicted_count : z.count} p`;
        if (isLowConf) {
          legTxt += ' [Low Confidence]';
        } else if (forecastMsg) {
          legTxt += ` (${forecastMsg})`;
        }
        text.textContent = legTxt;

        item.appendChild(swatch);
        item.appendChild(text);
        legendEl.appendChild(item);
      }

      if (detailsEl) {
        const row = document.createElement('div');
        row.className = 'trend-detail-row';
        if (isLowConf) {
          row.style.opacity = '0.7';
          row.style.background = '#0B0F19';
        }

        const left = document.createElement('div');
        left.style.fontWeight = '700';
        left.style.color = isLowConf ? '#94A3B8' : color;
        left.textContent = `${z.name || zId}${isLowConf ? ' (High Noise / Low Confidence)' : ''}`;

        const right = document.createElement('div');
        let detailsText = `Current: ${z.count || 0} p | Predicted (+30s): ${pred.predicted_count !== undefined ? pred.predicted_count : z.count} p | Confidence: ${pred.confidence || 'Low confidence'} | Trend: ${pred.trend || 'STABLE'}`;
        if (forecastMsg) {
          detailsText += ` | ⏳ Proactive Notice: ${forecastMsg}`;
        }
        right.textContent = detailsText;

        row.appendChild(left);
        row.appendChild(right);
        detailsEl.appendChild(row);
      }
    });
  }

  // Initial empty 8x8 grid render on load
  renderGridMatrix(gridMatrix, []);
  renderGridMatrix(gridMatrixLarge, []);

  // Initialize WebSocket Connection
  connectWebSocket();
})();