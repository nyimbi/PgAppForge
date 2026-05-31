/**
 * pgappforge ERD Designer — Cytoscape.js canvas logic.
 *
 * Dynamic data injected by the server as window.ERD_CONFIG before this
 * script loads:
 *   {apiBase, csrfToken, ddlEnabled, isAdmin, currentUser}
 *
 * Phases implemented:
 *   Phase 2: fcose layout, minimap, keyboard shortcuts, undo/redo,
 *             canvas search, PNG/SVG export, dark/light theme, column details
 *   Phase 3: Visual FK (edgehandles), inline column editor, M:N wizard,
 *             annotation nodes, index editor UI
 */

/* ── Configuration ────────────────────────────────────────────────────────── */
const CFG = window.ERD_CONFIG || {};
const API = CFG.apiBase || '/erd-designer';

/* ── Utilities ────────────────────────────────────────────────────────────── */

/** XSS-safe HTML escape. */
function _esc(s) {
  return String(s || '').replace(/[&<>"']/g, function(m) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
  });
}

/** Authenticated fetch to the ERD API with CSRF. */
function apiFetch(method, path, body) {
  var opts = {
    method: method,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': CFG.csrfToken || '',
    },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  return fetch(API + path, opts).then(function(r) { return r.json(); });
}

function setStatus(msg, cls) {
  var el = document.getElementById('status-bar');
  if (el) { el.textContent = msg; el.className = 'status-bar ' + (cls || ''); }
}

/* ── Cytoscape initialisation ─────────────────────────────────────────────── */

// Register extension layouts (loaded via CDN before this script)
if (window.cytoscapeFcose)   cytoscape.use(cytoscapeFcose);
if (window.cytoscapeDagre)   cytoscape.use(cytoscapeDagre);
if (window.cytoscapeEdgehandles) cytoscape.use(cytoscapeEdgehandles);

const cy = cytoscape({
  container: document.getElementById('cy'),
  style: [
    { selector: 'node[type="module"]',
      style: { 'label': 'data(label)', 'text-halign': 'center', 'text-valign': 'top',
               'font-size': '13px', 'font-weight': 'bold', 'color': 'var(--cy-text, #ecf0f1)',
               'text-margin-y': -6,
               'background-color': 'data(color)', 'background-opacity': 0.15,
               'border-width': 2, 'border-color': 'data(color)',
               'padding': '14px', 'shape': 'round-rectangle' } },
    { selector: 'node[type="table"]',
      style: { 'label': 'data(label)', 'text-halign': 'center', 'text-valign': 'center',
               'font-size': '11px', 'color': 'var(--cy-text, #ecf0f1)',
               'background-color': 'var(--cy-node-bg, #2c3e50)', 'border-width': 1.5,
               'border-color': 'data(color)', 'width': 120, 'height': 42,
               'shape': 'rectangle' } },
    { selector: 'node[type="table"]:selected',
      style: { 'background-color': 'var(--cy-node-sel, #34495e)', 'border-width': 3 } },
    { selector: 'node[type="annotation"]',
      style: { 'label': 'data(text)', 'text-halign': 'center', 'text-valign': 'center',
               'text-wrap': 'wrap', 'text-max-width': 160,
               'font-size': '11px', 'color': '#2c3e50',
               'background-color': '#f9e79f', 'border-width': 1, 'border-color': '#f0c040',
               'shape': 'round-rectangle', 'padding': '8px', 'width': 160, 'height': 60 } },
    { selector: 'edge[type="fk"]',
      style: { 'curve-style': 'bezier', 'target-arrow-shape': 'triangle',
               'line-color': '#555', 'target-arrow-color': '#555',
               'width': 1.5, 'label': 'data(label)',
               'font-size': '9px', 'color': '#777', 'text-background-opacity': 0 } },
    /* Diff overlay styles */
    { selector: 'node.diff-new',    style: { 'border-color': '#2ecc71', 'border-width': 4 } },
    { selector: 'node.diff-drop',   style: { 'border-color': '#e74c3c', 'border-width': 4 } },
    { selector: 'node.diff-alter',  style: { 'border-color': '#f39c12', 'border-width': 4 } },
  ],
  layout: { name: 'cose', animate: false },
  wheelSensitivity: 0.2,
});

/* ── Minimap (cytoscape-navigator) ───────────────────────────────────────── */
if (cy.navigator) {
  cy.navigator({ container: '#cy-nav', viewLiveFramerate: 0, thumbnailEventFramerate: 10 });
}

/* ── Theme toggle ─────────────────────────────────────────────────────────── */
let _theme = localStorage.getItem('erd-theme') || 'dark';

function applyTheme(t) {
  _theme = t;
  document.body.setAttribute('data-theme', t);
  localStorage.setItem('erd-theme', t);
  var isDark = t === 'dark';
  document.body.style.setProperty('--cy-text',     isDark ? '#ecf0f1' : '#2c3e50');
  document.body.style.setProperty('--cy-node-bg',  isDark ? '#2c3e50' : '#ffffff');
  document.body.style.setProperty('--cy-node-sel', isDark ? '#34495e' : '#d5e8d4');
  cy.style().update();
  var btn = document.getElementById('btn-theme');
  if (btn) btn.textContent = isDark ? '☀ Light' : '☾ Dark';
}

applyTheme(_theme);

/* ── Undo / redo stack ────────────────────────────────────────────────────── */
const _undoStack = [], _redoStack = [];

function pushUndo(op, inverseOp) {
  _undoStack.push({op: op, inv: inverseOp});
  _redoStack.length = 0;
  _updateUndoButtons();
}

function _updateUndoButtons() {
  var u = document.getElementById('btn-undo');
  var r = document.getElementById('btn-redo');
  if (u) u.disabled = _undoStack.length === 0;
  if (r) r.disabled = _redoStack.length === 0;
}

function undoAction() {
  if (!_undoStack.length) return;
  var item = _undoStack.pop();
  _redoStack.push(item);
  if (item.inv) {
    apiFetch('POST', '/api/schema/apply', [item.inv]).then(function(d) {
      setStatus(d.errors && d.errors.length ? '✗ Undo failed: ' + d.errors[0] : '↩ Undone', '');
      refreshCanvas();
    });
  }
  _updateUndoButtons();
}

function redoAction() {
  if (!_redoStack.length) return;
  var item = _redoStack.pop();
  _undoStack.push(item);
  apiFetch('POST', '/api/schema/apply', [item.op]).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ Redo failed: ' + d.errors[0] : '↪ Redone', '');
    refreshCanvas();
  });
  _updateUndoButtons();
}

_updateUndoButtons();

/* ── Keyboard shortcuts ───────────────────────────────────────────────────── */
document.addEventListener('keydown', function(e) {
  var tag = (document.activeElement || {}).tagName || '';
  if (['INPUT','TEXTAREA','SELECT'].includes(tag)) return; // don't intercept form fields

  if ((e.ctrlKey || e.metaKey) && e.key === 'z') { e.preventDefault(); undoAction(); return; }
  if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.shiftKey && e.key === 'Z'))) {
    e.preventDefault(); redoAction(); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
    e.preventDefault(); cy.$('*').select(); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    var s = document.getElementById('canvas-search');
    if (s) { s.focus(); s.select(); }
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'S') {
    e.preventDefault(); saveCurrentDesign(); return;
  }
  if (e.key === 'Escape') {
    cy.$(':selected').unselect();
    hideContextMenu();
    closeAllModals();
    return;
  }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    var sel = cy.$(':selected');
    if (!sel.length) return;
    var tables = sel.filter('node[type="table"]');
    if (tables.length && !confirm('Delete ' + tables.length + ' table(s)? This cannot be undone from the canvas.')) return;
    sel.remove();
    return;
  }
});

function closeAllModals() {
  document.querySelectorAll('.erd-modal').forEach(function(m) { m.style.display = 'none'; });
}

/* ── Collapsed module tracking ────────────────────────────────────────────── */
const collapsed = {};

function _collapseModule(modId) {
  var children = cy.nodes('[parent="' + modId + '"]');
  if (collapsed[modId]) {
    children.style({ 'display': 'element' });
    cy.edges().style({ 'display': 'element' });
    collapsed[modId] = false;
  } else {
    var childIds = new Set(children.map(function(n){ return n.id(); }));
    children.style({ 'display': 'none' });
    cy.edges().filter(function(e) {
      return childIds.has(e.data('source')) || childIds.has(e.data('target'));
    }).style({ 'display': 'none' });
    collapsed[modId] = true;
  }
}

cy.on('dblclick', 'node[type="module"]', function(e) { _collapseModule(e.target.id()); });

/* ── Info panel (column details) ─────────────────────────────────────────── */
cy.on('tap', 'node[type="table"]', function(e) {
  var d = e.target.data();
  var cols = (d.columns || []).map(function(c) {
    var badges = '';
    if (c.pk)     badges += '<span class="col-badge pk">PK</span>';
    if (c.fk)     badges += '<span class="col-badge fk">FK</span>';
    if (c.unique) badges += '<span class="col-badge uq">UQ</span>';
    return '<div class="col-row">' + badges +
           '<span class="col-name">' + _esc(c.name) + '</span>' +
           '<span class="col-type">' + _esc(c.type || '') + '</span></div>';
  }).join('');
  var panel = document.getElementById('info-panel');
  if (panel) {
    panel.innerHTML = '<div class="ip-title">' + _esc(d.label) + '</div>' +
                      '<div class="ip-cols">' + cols + '</div>' +
                      '<div class="ip-actions">' +
                      '<button onclick="openColumnEditor(\'' + _esc(e.target.id()) + '\')" class="ip-btn">✎ Edit</button>' +
                      '</div>';
    panel.style.display = 'block';
  }
});

cy.on('tap', function(e) {
  if (e.target === cy) {
    var p = document.getElementById('info-panel');
    if (p) p.style.display = 'none';
    hideContextMenu();
  }
});

/* Double-click table → open column editor */
cy.on('dbltap', 'node[type="table"]', function(e) {
  openColumnEditor(e.target.id());
});

/* ── Context menu ─────────────────────────────────────────────────────────── */
let _ctxTarget = null;

cy.on('cxttap', 'node', function(e) {
  _ctxTarget = e.target;
  var cm = document.getElementById('context-menu');
  cm.style.display = 'block';
  cm.style.left = e.originalEvent.clientX + 'px';
  cm.style.top  = e.originalEvent.clientY + 'px';
  var foldBtn = document.getElementById('cm-fold');
  if (foldBtn) foldBtn.textContent =
    e.target.data('type') === 'module'
      ? (collapsed[e.target.id()] ? '▸ Unfold' : '▾ Fold')
      : '▾ Fold module';
  // Show M:N option only when 2 tables selected
  var mn = document.getElementById('cm-mn');
  if (mn) mn.style.display = cy.$('node[type="table"]:selected').length === 2 ? '' : 'none';
});

/* Right-click empty space → add annotation */
cy.on('cxttap', function(e) {
  if (e.target !== cy) return;
  var pos = e.position;
  cy.add({ data: { id: 'ann_' + Date.now(), type: 'annotation', text: '📝 Note' }, position: pos });
});

function hideContextMenu() {
  var cm = document.getElementById('context-menu');
  if (cm) cm.style.display = 'none';
}

document.addEventListener('click', function(e) {
  if (!e.target.closest('#context-menu')) hideContextMenu();
});

(function wireContextMenu() {
  var cm = document.getElementById('cm-fold');
  if (cm) cm.onclick = function() {
    if (_ctxTarget) {
      var mid = _ctxTarget.data('type') === 'module'
        ? _ctxTarget.id() : _ctxTarget.data('parent');
      if (mid) _collapseModule(mid);
    }
    hideContextMenu();
  };

  var rm = document.getElementById('cm-remove');
  if (rm) rm.onclick = function() {
    if (_ctxTarget) {
      if (_ctxTarget.data('type') === 'module') {
        var modId = _ctxTarget.id();
        cy.nodes('[parent="' + modId + '"]').remove();
        cy.edges().filter(function(e) {
          return e.source().data('parent') === modId || e.target().data('parent') === modId;
        }).remove();
      }
      _ctxTarget.remove();
    }
    hideContextMenu();
  };

  var fit = document.getElementById('cm-fit-sel');
  if (fit) fit.onclick = function() {
    var sel = cy.$(':selected');
    if (sel.length) cy.fit(sel, 40);
    hideContextMenu();
  };

  var mn = document.getElementById('cm-mn');
  if (mn) mn.onclick = function() { openMNWizard(); hideContextMenu(); };
})();

/* ── Visual FK — edge handles ─────────────────────────────────────────────── */
var _eh = null;
if (cy.edgehandles) {
  _eh = cy.edgehandles({
    canConnect: function(src, tgt) {
      return src.data('type') === 'table' && tgt.data('type') === 'table' && src !== tgt;
    },
    edgeParams: function() { return { data: { type: 'fk', label: 'FK' } }; },
    complete: function(src, tgt, addedEdge) {
      addedEdge.remove(); // remove preview edge — we'll add real one after user picks columns
      openFKModal(src.id(), tgt.id());
    },
  });
  _eh.enable();
}

/* ── FK modal ─────────────────────────────────────────────────────────────── */
function openFKModal(srcId, tgtId) {
  var src = cy.getElementById(srcId), tgt = cy.getElementById(tgtId);
  if (!src.length || !tgt.length) return;
  var srcCols = (src.data('columns') || []).map(function(c){ return c.name; });
  var tgtCols = (tgt.data('columns') || []).map(function(c){ return c.name; });
  var m = document.getElementById('fk-modal');
  if (!m) return;
  document.getElementById('fk-src-table').textContent = srcId;
  document.getElementById('fk-tgt-table').textContent = tgtId;
  _populateSelect('fk-src-col', srcCols);
  _populateSelect('fk-tgt-col', tgtCols, 'id');
  m.style.display = 'flex';
  m.dataset.src = srcId;
  m.dataset.tgt = tgtId;
}

document.addEventListener('DOMContentLoaded', function() {
  var okBtn = document.getElementById('fk-ok');
  if (okBtn) okBtn.onclick = function() {
    var m = document.getElementById('fk-modal');
    var srcId = m.dataset.src, tgtId = m.dataset.tgt;
    var col = document.getElementById('fk-src-col').value;
    var ref = document.getElementById('fk-tgt-col').value;
    if (!col || !ref) return;
    var op = { op: 'add_fk', table: srcId, column: col, ref_table: tgtId, ref_column: ref };
    apiFetch('POST', '/api/schema/apply', [op]).then(function(d) {
      m.style.display = 'none';
      if (!d.errors || !d.errors.length) {
        cy.add({ data: { id: srcId + '_' + col + '_fk', source: srcId, target: tgtId,
                          type: 'fk', label: col + ' → ' + ref } });
        pushUndo(op, { op: 'drop_fk', table: srcId,
                        constraint_name: srcId + '_' + col + '_' + tgtId + '_fkey' });
        setStatus('FK added: ' + srcId + '.' + col + ' → ' + tgtId + '.' + ref);
      } else {
        setStatus('✗ FK error: ' + d.errors[0]);
      }
    });
  };
});

/* ── Inline column editor modal ───────────────────────────────────────────── */
function openColumnEditor(tableId) {
  var node = cy.getElementById(tableId);
  if (!node.length) return;
  var cols = node.data('columns') || [];
  var m = document.getElementById('col-editor-modal');
  if (!m) return;
  m.dataset.tableId = tableId;
  document.getElementById('col-editor-title').textContent = 'Edit: ' + _esc(tableId);
  var tbody = document.getElementById('col-editor-rows');
  tbody.innerHTML = '';
  cols.forEach(function(c) { _addColEditorRow(tbody, c); });
  m.style.display = 'flex';
}

function _addColEditorRow(tbody, c) {
  c = c || {};
  var tr = document.createElement('tr');
  tr.innerHTML =
    '<td><input class="ced-name" value="' + _esc(c.name || '') + '" placeholder="col_name"></td>' +
    '<td><input class="ced-type" value="' + _esc(c.type || 'TEXT') + '" list="pg-types-list" placeholder="TEXT"></td>' +
    '<td><input type="checkbox" class="ced-pk"' + (c.pk  ? ' checked' : '') + '></td>' +
    '<td><input type="checkbox" class="ced-uq"' + (c.unique ? ' checked' : '') + '></td>' +
    '<td><input type="checkbox" class="ced-nn"' + (!c.nullable ? ' checked' : '') + '></td>' +
    '<td><input class="ced-def" value="' + _esc(c.default != null ? c.default : '') + '" placeholder="default"></td>' +
    '<td><button onclick="this.closest(\'tr\').remove()" class="del-btn">✕</button></td>';
  tbody.appendChild(tr);
}

document.addEventListener('DOMContentLoaded', function() {
  var addBtn = document.getElementById('col-editor-add');
  if (addBtn) addBtn.onclick = function() {
    _addColEditorRow(document.getElementById('col-editor-rows'), {});
  };

  var saveBtn = document.getElementById('col-editor-save');
  if (saveBtn) saveBtn.onclick = function() {
    var m = document.getElementById('col-editor-modal');
    var tableId = m.dataset.tableId;
    var node = cy.getElementById(tableId);
    if (!node.length) { m.style.display = 'none'; return; }
    var existing = node.data('columns') || [];
    var existingNames = new Set(existing.map(function(c){ return c.name; }));
    var ops = [];
    document.querySelectorAll('#col-editor-rows tr').forEach(function(tr) {
      var name = tr.querySelector('.ced-name').value.trim();
      var type = tr.querySelector('.ced-type').value.trim() || 'TEXT';
      var pk   = tr.querySelector('.ced-pk').checked;
      var uq   = tr.querySelector('.ced-uq').checked;
      var nn   = tr.querySelector('.ced-nn').checked;
      var def  = tr.querySelector('.ced-def').value.trim() || null;
      if (!name) return;
      if (!existingNames.has(name)) {
        ops.push({ op: 'add_column', table: tableId, column: {
          name: name, type: type, pk: pk, unique: uq, nullable: !nn, default: def
        }});
      }
    });
    if (!ops.length) { m.style.display = 'none'; return; }
    apiFetch('POST', '/api/schema/apply', ops).then(function(d) {
      m.style.display = 'none';
      setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Columns updated');
      if (!d.errors || !d.errors.length) refreshCanvas();
    });
  };
});

/* ── M:N junction wizard ──────────────────────────────────────────────────── */
function openMNWizard() {
  var sel = cy.$('node[type="table"]:selected');
  if (sel.length !== 2) { alert('Select exactly 2 tables first.'); return; }
  var a = sel[0].id(), b = sel[1].id();
  var name = a + '_' + b;
  var custom = prompt('Junction table name:', name);
  if (!custom) return;
  var ops = [
    { op: 'create_table', table: custom, columns: [
        { name: 'id', type: 'SERIAL', pk: true },
        { name: a + '_id', type: 'INTEGER', nullable: false, fk: a + '.id' },
        { name: b + '_id', type: 'INTEGER', nullable: false, fk: b + '.id' },
    ]},
  ];
  apiFetch('POST', '/api/schema/apply', ops).then(function(d) {
    if (!d.errors || !d.errors.length) {
      setStatus('✓ Junction table ' + custom + ' created');
      refreshCanvas();
    } else {
      setStatus('✗ ' + d.errors[0]);
    }
  });
}

/* ── Canvas search ────────────────────────────────────────────────────────── */
function canvasSearch(q) {
  if (!q) { cy.nodes().style({'border-width': null}); return; }
  var lq = q.toLowerCase();
  cy.nodes().forEach(function(n) {
    var match = (n.data('label') || '').toLowerCase().includes(lq);
    if (match) {
      n.style({'border-width': 4, 'border-color': '#e74c3c'});
      cy.animate({ zoom: 1.5, pan: {
        x: cy.width() / 2 - n.position().x * 1.5,
        y: cy.height() / 2 - n.position().y * 1.5
      }}, { duration: 400 });
    } else {
      n.style({'border-width': null});
    }
  });
}

/* ── Canvas export (PNG / SVG) ────────────────────────────────────────────── */
function exportCanvas(fmt) {
  var data = fmt === 'png' ? cy.png({ full: true, scale: 2 }) : cy.svg({ full: true });
  var a = document.createElement('a');
  a.href = fmt === 'svg' ? 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(data) : data;
  a.download = 'schema.' + fmt;
  a.click();
}

/* ── Module collapse tracking ─────────────────────────────────────────────── */
function filterModules(q) {
  var lq = q.toLowerCase();
  document.querySelectorAll('.mod-item').forEach(function(el) {
    var match = (el.dataset.label || '').toLowerCase().includes(lq)
             || (el.dataset.domain || '').toLowerCase().includes(lq);
    el.style.display = match ? '' : 'none';
  });
  document.querySelectorAll('.domain-group').forEach(function(g) {
    var visible = g.querySelectorAll('.mod-item:not([style*="none"])').length;
    g.style.display = visible > 0 ? '' : 'none';
    if (q && visible > 0) { var di = g.querySelector('.domain-items'); if (di) di.classList.remove('collapsed'); }
  });
}

function toggleDomain(header) {
  var items = header.nextElementSibling;
  items.classList.toggle('collapsed');
  var arrow = header.querySelector('span:last-child');
  if (arrow) arrow.textContent = items.classList.contains('collapsed') ? '▸' : '▾';
}

/* ── Layout ───────────────────────────────────────────────────────────────── */
function relayout() {
  var nodeCount = cy.nodes().length;
  var layoutName = 'cose';
  if (cytoscapeFcose && nodeCount > 30) layoutName = 'fcose';
  cy.layout({
    name: layoutName,
    animate: nodeCount < 50,
    animationDuration: 400,
    nodeRepulsion: 8000,
    idealEdgeLength: 80,
    edgeElasticity: 32,
    // fcose-specific
    quality: 'default',
    randomize: false,
  }).run();
}

/* ── Schema diff overlay ──────────────────────────────────────────────────── */
function showDiff(ops) {
  apiFetch('POST', '/api/schema/diff', {ops: ops}).then(function(d) {
    cy.nodes().removeClass('diff-new diff-drop diff-alter');
    (d.tables_added   || []).forEach(function(t){ cy.getElementById(t).addClass('diff-new'); });
    (d.tables_dropped || []).forEach(function(t){ cy.getElementById(t).addClass('diff-drop'); });
    (d.tables_altered || []).forEach(function(t){ cy.getElementById(t).addClass('diff-alter'); });
    var sqlEl = document.getElementById('diff-sql-preview');
    if (sqlEl) sqlEl.textContent = (d.sql || []).join('\n');
    var m = document.getElementById('diff-modal');
    if (m) m.style.display = 'flex';
  });
}

function clearDiff() {
  cy.nodes().removeClass('diff-new diff-drop diff-alter');
}

/* ── Load ERP module onto canvas ──────────────────────────────────────────── */
const _loadedModules = {};

function addModule(key) {
  setStatus('Loading ' + key + '…');
  apiFetch('GET', '/api/all-templates').then(function(d) {
    var filtered = (d.elements || []).filter(function(el) {
      return el.data.id === 'mod_' + key
          || el.data.parent === 'mod_' + key
          || (el.data.source && el.data.target);
    });
    var toAdd = filtered.filter(function(el){ return !cy.getElementById(el.data.id).length; });
    cy.batch(function() { cy.add(toAdd); });
    relayout();
    _loadedModules[key] = true;
    setStatus('Added ' + key + ' | ' + cy.nodes().length + ' nodes');
  });
}

/* ── Load live schema ─────────────────────────────────────────────────────── */
function loadLiveSchema(schema) {
  var qs = schema ? '?schema=' + encodeURIComponent(schema) : '';
  setStatus('Loading live schema…');
  apiFetch('GET', '/api/live-schema' + qs).then(function(d) {
    if (d.error) { setStatus('✗ ' + d.error); return; }
    var toAdd = (d.elements || []).filter(function(el){ return !cy.getElementById(el.data.id).length; });
    cy.batch(function() { cy.add(toAdd); });
    relayout();
    setStatus('Live schema: ' + cy.nodes().length + ' nodes, ' + cy.edges().length + ' edges');
  });
}

/* Reload canvas from live DB (used after apply_changes) */
function refreshCanvas() {
  cy.elements().remove();
  loadLiveSchema();
}

/* ── PostgreSQL schema switcher ───────────────────────────────────────────── */
function loadSchemaList() {
  apiFetch('GET', '/api/schema-list').then(function(d) {
    var sel = document.getElementById('schema-switcher');
    if (!sel) return;
    sel.innerHTML = '';
    (d.schemas || ['public']).forEach(function(s) {
      var opt = document.createElement('option');
      opt.value = s; opt.textContent = s;
      if (s === 'public') opt.selected = true;
      sel.appendChild(opt);
    });
  }).catch(function(){});
}
loadSchemaList();

/* ── Design save / load ───────────────────────────────────────────────────── */
let _currentDesignId = null;
let _autoSaveTimer   = null;

function saveCurrentDesign(name) {
  var canvasJson = cy.json();
  var payload = { canvas_json: canvasJson, schema_json: {} };
  if (name) payload.name = name;
  if (_currentDesignId) {
    apiFetch('PUT', '/api/designs/' + _currentDesignId, payload).then(function() {
      setStatus('✓ Saved');
    });
  } else {
    var n = name || prompt('Design name:', 'Untitled');
    if (!n) return;
    payload.name = n;
    apiFetch('POST', '/api/designs', payload).then(function(d) {
      if (d.ok) { _currentDesignId = d.id; setStatus('✓ Saved as ' + d.name); }
    });
  }
}

function scheduleAutoSave() {
  clearTimeout(_autoSaveTimer);
  if (_currentDesignId) {
    _autoSaveTimer = setTimeout(function() { saveCurrentDesign(); }, 3000);
  }
}

cy.on('add remove move', scheduleAutoSave);

function loadDesign(id) {
  apiFetch('GET', '/api/designs/' + id).then(function(d) {
    if (d.error) { alert(d.error); return; }
    _currentDesignId = d.id;
    cy.elements().remove();
    if (d.canvas_json && d.canvas_json.elements) {
      cy.json(d.canvas_json);
    }
    setStatus('Loaded: ' + _esc(d.name));
  });
}

/* ── FK suggestion ────────────────────────────────────────────────────────── */
function suggestFKs() {
  apiFetch('GET', '/api/ai/suggest-fks').then(function(d) {
    var list = d.suggestions || [];
    if (!list.length) { alert('No FK suggestions found.'); return; }
    var m = document.getElementById('fk-suggest-modal');
    if (!m) return;
    var ul = document.getElementById('fk-suggest-list');
    ul.innerHTML = '';
    list.forEach(function(op, i) {
      var li = document.createElement('li');
      li.innerHTML = '<label><input type="checkbox" checked data-i="' + i + '"> ' +
        _esc(op.table) + '.' + _esc(op.column) + ' → ' + _esc(op.ref_table) + '.' + _esc(op.ref_column || 'id') + '</label>';
      li.dataset.op = JSON.stringify(op);
      ul.appendChild(li);
    });
    m._allSuggestions = list;
    m.style.display = 'flex';
  });
}

document.addEventListener('DOMContentLoaded', function() {
  var applyFKs = document.getElementById('fk-suggest-apply');
  if (applyFKs) applyFKs.onclick = function() {
    var m = document.getElementById('fk-suggest-modal');
    var ops = [];
    m.querySelectorAll('input[type="checkbox"]:checked').forEach(function(cb) {
      var i = parseInt(cb.dataset.i);
      ops.push(m._allSuggestions[i]);
    });
    if (!ops.length) { m.style.display = 'none'; return; }
    apiFetch('POST', '/api/schema/apply', ops).then(function(d) {
      m.style.display = 'none';
      setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ ' + ops.length + ' FK(s) added');
      if (!d.errors || !d.errors.length) refreshCanvas();
    });
  };
});

/* ── Normalization analysis ───────────────────────────────────────────────── */
function runNormalizationAnalysis() {
  apiFetch('GET', '/api/analysis/normalize').then(function(d) {
    var warnings = d.warnings || [];
    cy.nodes().removeClass('analysis-warn');
    warnings.forEach(function(w) { cy.getElementById(w.table).addClass('analysis-warn'); });
    var m = document.getElementById('analysis-modal');
    if (!m) return;
    var ul = document.getElementById('analysis-list');
    ul.innerHTML = warnings.length
      ? warnings.map(function(w) {
          return '<li><b>' + _esc(w.level) + '</b> — <i>' + _esc(w.table) + '</i>: ' +
                 _esc(w.message) + '<br><small>💡 ' + _esc(w.suggestion || '') + '</small></li>';
        }).join('')
      : '<li>No normalization issues detected.</li>';
    m.style.display = 'flex';
  });
}

/* ── Index recommendations ────────────────────────────────────────────────── */
function recommendIndexes() {
  apiFetch('GET', '/api/analysis/recommend-indexes').then(function(d) {
    var ops = d.recommendations || [];
    var m = document.getElementById('index-rec-modal');
    if (!m) return;
    var ul = document.getElementById('index-rec-list');
    ul.innerHTML = '';
    ops.forEach(function(op, i) {
      var li = document.createElement('li');
      li.innerHTML = '<label><input type="checkbox" checked data-i="' + i + '"> CREATE INDEX ON ' +
        _esc(op.table) + ' (' + _esc((op.columns || []).join(', ')) + ')' +
        (op.unique ? ' UNIQUE' : '') + (op.reason ? ' — <small>' + _esc(op.reason) + '</small>' : '') +
        '</label>';
      ul.appendChild(li);
    });
    m._allRec = ops;
    m.style.display = 'flex';
  });
}

document.addEventListener('DOMContentLoaded', function() {
  var applyIdx = document.getElementById('index-rec-apply');
  if (applyIdx) applyIdx.onclick = function() {
    var m = document.getElementById('index-rec-modal');
    var ops = [];
    m.querySelectorAll('input:checked').forEach(function(cb) {
      ops.push(m._allRec[parseInt(cb.dataset.i)]);
    });
    if (!ops.length) { m.style.display = 'none'; return; }
    apiFetch('POST', '/api/schema/apply', ops).then(function(d) {
      m.style.display = 'none';
      setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ ' + ops.length + ' index(es) created');
    });
  };
});

/* ── AI schema generation ─────────────────────────────────────────────────── */
function aiGenerateSchema() {
  var m = document.getElementById('ai-gen-modal');
  if (m) m.style.display = 'flex';
}

document.addEventListener('DOMContentLoaded', function() {
  var go = document.getElementById('ai-gen-go');
  if (go) go.onclick = function() {
    var desc = (document.getElementById('ai-gen-desc') || {}).value || '';
    if (!desc.trim()) return;
    setStatus('AI generating schema…');
    apiFetch('POST', '/api/ai/generate-schema', { description: desc }).then(function(d) {
      var m = document.getElementById('ai-gen-modal');
      if (m) m.style.display = 'none';
      if (d.error) { setStatus('✗ AI: ' + d.error); return; }
      // Apply ops to canvas (no DB hit yet — dry-run visualise)
      apiFetch('POST', '/api/schema/apply?dry_run=1', d.ops || []).then(function(dd) {
        setStatus(dd.would_apply + ' tables would be created. Click Apply to execute.');
        var confirmBtn = document.getElementById('ai-gen-confirm');
        if (confirmBtn) {
          confirmBtn.style.display = '';
          confirmBtn._ops = d.ops;
          confirmBtn.onclick = function() {
            apiFetch('POST', '/api/schema/apply', d.ops || []).then(function(r) {
              setStatus(r.errors && r.errors.length ? '✗ ' + r.errors[0] : '✓ AI schema applied');
              refreshCanvas();
            });
          };
        }
      });
    });
  };
});

/* ── Generate app ─────────────────────────────────────────────────────────── */
function generateApp() {
  var name = (document.getElementById('gen-name') || {}).value || 'GeneratedApp';
  setStatus('Generating app…');
  apiFetch('POST', '/api/generate-app', { app_name: name }).then(function(d) {
    setStatus(d.status === 'success'
      ? '✓ App: ' + d.files_generated + ' files → ' + d.output_dir
      : '✗ ' + (d.error || 'error'));
  });
}

/* ── Annotation double-click to edit text ─────────────────────────────────── */
cy.on('dbltap', 'node[type="annotation"]', function(e) {
  var node = e.target;
  var newText = prompt('Edit note:', node.data('text') || '');
  if (newText !== null) node.data('text', newText);
});

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function _populateSelect(id, options, defaultVal) {
  var sel = document.getElementById(id);
  if (!sel) return;
  sel.innerHTML = options.map(function(o) {
    return '<option value="' + _esc(o) + '"' + (o === defaultVal ? ' selected' : '') + '>' + _esc(o) + '</option>';
  }).join('');
}

/* ── Collaboration: Server-Sent Events ────────────────────────────────────── */
let _sseSource = null;
var _sseBackoff = 1000;

function connectSSE(designId) {
  if (_sseSource) _sseSource.close();
  var es = new EventSource(API + '/api/events/' + designId);
  _sseSource = es;
  es.onopen = function() {
    _sseBackoff = 1000;
  };
  es.onmessage = function(e) {
    try {
      var data = JSON.parse(e.data);
      if (data.type === 'update' && data.canvas_json) {
        // Merge remote changes (simple strategy: reload canvas)
        if (data.user !== CFG.currentUser) {
          cy.elements().remove();
          cy.json(data.canvas_json);
          setStatus('↺ Updated by ' + _esc(data.user));
        }
      }
    } catch(_) {}
  };
  es.onerror = function() {
    es.close();
    _sseSource = null;
    setTimeout(function() {
      if (_currentDesignId) connectSSE(_currentDesignId);
    }, _sseBackoff);
    _sseBackoff = Math.min(_sseBackoff * 2, 30000);
  };
}

// Auto-connect if a design is pre-loaded
if (CFG.designId) {
  _currentDesignId = CFG.designId;
  connectSSE(CFG.designId);
}

/* ── Trigger / Function Panel ─────────────────────────────────────────────── */

var _triggerTemplates = null;
var _selectedTplKey   = null;

function openTriggerPanel(tab) {
  var m = document.getElementById('trigger-modal');
  if (m) { m.style.display = 'flex'; switchTriggerTab(tab || 'templates'); }
}

/** All 10 tabs: triggers, live, functions, editor, domains, evtrig, matviews, views, policies, objtpl */
var _ALL_TABS = ['templates','live','functions','editor',
                 'domains','evtrig','matviews','views','policies','objtpl'];

function switchTriggerTab(tab) {
  _ALL_TABS.forEach(function(t) {
    var p  = document.getElementById('tpanel-' + t);
    var bt = document.getElementById('tab-' + t);
    if (p)  p.style.display = t === tab ? '' : 'none';
    if (bt) bt.className = bt.className.replace(' active','') + (t === tab ? ' active' : '');
  });
  // Lazy-load on first open
  if (tab === 'templates') loadTriggerTemplates();
  if (tab === 'live')      loadLiveTriggers();
  if (tab === 'functions') loadFunctions();
  if (tab === 'domains')   loadDomains();
  if (tab === 'evtrig')    loadEventTriggers();
  if (tab === 'matviews')  loadMatViews();
  if (tab === 'views')     loadViews();
  if (tab === 'policies')  loadPolicies();
  if (tab === 'objtpl')    loadObjectTemplates();
}

/* Templates grid */
function loadTriggerTemplates() {
  if (_triggerTemplates) { renderTplGrid(_triggerTemplates); return; }
  apiFetch('GET', '/api/triggers/templates').then(function(d) {
    _triggerTemplates = d.templates || [];
    renderTplGrid(_triggerTemplates);
  });
}

function renderTplGrid(templates, category) {
  var grid = document.getElementById('tpl-grid');
  if (!grid) return;
  var filtered = category && category !== 'all'
    ? templates.filter(function(t){ return t.category === category; })
    : templates;
  if (!filtered.length) { grid.innerHTML = '<div style="color:#7f8c8d">No templates in this category.</div>'; return; }
  grid.innerHTML = filtered.map(function(t) {
    var icon = t.icon ? '<i class="fas ' + _esc(t.icon) + ' me-1"></i>' : '&#9889;';
    var cardId = 'tplcard-' + _esc(t.key || '');
    return '<div class="tpl-card" id="' + cardId + '" onclick="selectTemplate(\'' + _esc(t.key || '') + '\')">' +
      '<h6>' + icon + ' ' + _esc(t.label) + '</h6>' +
      '<p>' + _esc(t.description || '') + '</p>' +
      (t.category ? '<span style="font-size:.68em;color:#7f8c8d">' + _esc(t.category) + '</span>' : '') +
      '</div>';
  }).join('');
}

function filterTplCategory(cat) {
  document.querySelectorAll('.tcat').forEach(function(b){
    b.classList.toggle('active', b.dataset.cat === cat);
  });
  renderTplGrid(_triggerTemplates || [], cat);
}

function selectTemplate(templateKey) {
  _selectedTplKey = templateKey;
  document.querySelectorAll('.tpl-card').forEach(function(c){
    c.classList.toggle('selected', c.id === 'tplcard-' + templateKey);
  });
  var tmpl = (_triggerTemplates || []).find(function(t){ return t.key === templateKey; });
  if (!tmpl) return;

  document.getElementById('tpl-params-title').textContent = tmpl.label;
  document.getElementById('tpl-params-desc').textContent  = tmpl.description || '';
  document.getElementById('tpl-sql-preview').textContent  = '';

  var fields = document.getElementById('tpl-params-fields');
  fields.innerHTML = (tmpl.params || []).map(function(p) {
    var dflt = (tmpl.defaults || {})[p] || '';
    if (p === 'table') {
      var sel = cy.$('node[type="table"]:selected');
      if (sel.length === 1) dflt = sel[0].id();
    }
    return '<div><label style="font-size:.75em;color:#7f8c8d">' + _esc(p) + '</label>' +
      '<input id="tpl-param-' + _esc(p) + '" class="form-control input-sm" ' +
      'style="background:#253545;color:#ecf0f1;border-color:#445566" value="' + _esc(dflt) + '"></div>';
  }).join('');

  document.getElementById('tpl-params-form').style.display = '';
  document.getElementById('tpl-apply-btn').onclick = function() { applyTriggerTemplate(); };
}

function _getTplParams() {
  var tmpl = (_triggerTemplates || []).find(function(t){ return t.key === _selectedTplKey; });
  if (!tmpl) return null;
  var params = { template_key: _selectedTplKey };
  (tmpl.params || []).forEach(function(p) {
    var el = document.getElementById('tpl-param-' + p);
    if (el) params[p] = el.value.trim();
  });
  return params;
}

function previewTriggerTemplate() {
  var tmpl = (_triggerTemplates || []).find(function(t){ return t.key === _selectedTplKey; });
  var params = _getTplParams();
  if (!tmpl || !params) return;
  var sql = [tmpl.function_sql || '', tmpl.trigger_sql || ''].filter(Boolean).join('\n\n');
  Object.keys(params).forEach(function(k) {
    sql = sql.split('{' + k + '}').join(params[k]);
  });
  document.getElementById('tpl-sql-preview').textContent = sql || '(preview after applying)';
}

function applyTriggerTemplate() {
  var params = _getTplParams();
  if (!params) return;
  setStatus('Applying trigger template…');
  apiFetch('POST', '/api/triggers/apply-template', params).then(function(d) {
    if (d.errors && d.errors.length) {
      setStatus('✗ Template error: ' + d.errors[0]);
    } else {
      setStatus('✓ Trigger applied: ' + _selectedTplKey);
      document.getElementById('tpl-params-form').style.display = 'none';
      loadLiveTriggers();
    }
  });
}

/* Live triggers */
function loadLiveTriggers() {
  var tbl  = (document.getElementById('trigger-table-filter') || {}).value || '';
  var qs   = tbl ? '?table=' + encodeURIComponent(tbl) : '';
  var list = document.getElementById('live-triggers-list');
  if (list) list.innerHTML = '<div style="color:#7f8c8d">Loading…</div>';
  apiFetch('GET', '/api/triggers/list' + qs).then(function(d) {
    var rows = d.triggers || [];
    if (!list) return;
    if (!rows.length) { list.innerHTML = '<div style="color:#7f8c8d">No triggers found.</div>'; return; }
    list.innerHTML = rows.map(function(t) {
      return '<div class="trigger-row">' +
        '<span><b>' + _esc(t.trigger_name) + '</b> on <i>' + _esc(t.event_object_table) + '</i>' +
        ' (' + _esc(t.event_manipulation) + ' ' + _esc(t.action_timing) + ')</span>' +
        '<button class="btn btn-xs btn-danger" onclick="dropTrigger(' +
        JSON.stringify(t.event_object_table) + ',' + JSON.stringify(t.trigger_name) +
        ')">Drop</button></div>';
    }).join('');
  });
}

function dropTrigger(table, triggerName) {
  if (!confirm('Drop trigger "' + triggerName + '" from "' + table + '"?')) return;
  apiFetch('POST', '/api/triggers/drop', {table: table, trigger_name: triggerName}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Dropped: ' + triggerName);
    loadLiveTriggers();
  });
}

/* Functions list */
function loadFunctions() {
  var schema = (document.getElementById('fn-schema-filter') || {}).value || 'public';
  var list   = document.getElementById('functions-list');
  var src    = document.getElementById('fn-source-view');
  if (src) src.style.display = 'none';
  if (list) list.innerHTML = '<div style="color:#7f8c8d">Loading…</div>';
  apiFetch('GET', '/api/functions/list?schema=' + encodeURIComponent(schema)).then(function(d) {
    var fns = d.functions || [];
    if (!list) return;
    if (!fns.length) { list.innerHTML = '<div style="color:#7f8c8d">No functions found.</div>'; return; }
    list.innerHTML = fns.map(function(f) {
      return '<div class="fn-row" onclick="loadFunctionSource(' +
        JSON.stringify(f.name) + ',' + JSON.stringify(schema) + ',' + JSON.stringify(f.args || '') + ')">' +
        '<span><b>' + _esc(f.name) + '</b>(' + _esc(f.args || '') + ') → <i>' + _esc(f.returns || 'void') + '</i></span>' +
        '<span style="color:#7f8c8d;font-size:.75em">' + _esc(f.language || '') + '</span>' +
        '</div>';
    }).join('');
  });
}

function loadFunctionSource(name, schema, args) {
  var srcView = document.getElementById('fn-source-view');
  document.getElementById('fn-source-name').textContent = schema + '.' + name + '(' + args + ')';
  document.getElementById('fn-source-code').textContent = 'Loading…';
  srcView.style.display = '';
  apiFetch('GET', '/api/functions/source?name=' + encodeURIComponent(name) + '&schema=' + encodeURIComponent(schema))
    .then(function(d) { document.getElementById('fn-source-code').textContent = d.source || '(unavailable)'; });
  document.getElementById('fn-drop-btn').onclick = function() {
    if (!confirm('Drop function ' + schema + '.' + name + '?')) return;
    apiFetch('POST', '/api/functions/drop', {name: name, args: args, schema: schema}).then(function(d) {
      setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Dropped: ' + name);
      srcView.style.display = 'none';
      loadFunctions();
    });
  };
  // Copy into editor
  document.getElementById('fn-edit-name').value   = name;
  document.getElementById('fn-edit-schema').value = schema;
  document.getElementById('fn-edit-args').value   = args;
}

/* Function editor */
function clearFunctionEditor() {
  ['fn-edit-name','fn-edit-args','fn-edit-body'].forEach(function(id){
    var el = document.getElementById(id); if (el) el.value = '';
  });
  var s = document.getElementById('fn-edit-schema'); if (s) s.value = 'public';
  var r = document.getElementById('fn-edit-returns'); if (r) r.value = 'TRIGGER';
}

function submitCustomFunction() {
  var payload = {
    name:     (document.getElementById('fn-edit-name')    || {}).value || '',
    schema:   (document.getElementById('fn-edit-schema')  || {}).value || 'public',
    args:     (document.getElementById('fn-edit-args')    || {}).value || '',
    returns:  (document.getElementById('fn-edit-returns') || {}).value || 'void',
    body:     (document.getElementById('fn-edit-body')    || {}).value || '',
    language: 'plpgsql',
  };
  if (!payload.name || !payload.body) { alert('Name and body are required.'); return; }
  setStatus('Creating function ' + payload.name + '…');
  apiFetch('POST', '/api/functions/create', payload).then(function(d) {
    if (d.errors && d.errors.length) {
      setStatus('✗ Function error: ' + d.errors[0]);
    } else {
      setStatus('✓ Function created: ' + payload.name);
      clearFunctionEditor();
      loadFunctions();
      switchTriggerTab('functions');
    }
  });
}

/* ── Object Template grid ──────────────────────────────────────────────────── */
var _objectTemplates = null;
var _selectedObjTplKey = null;

function loadObjectTemplates() {
  if (_objectTemplates) { renderObjTplGrid(_objectTemplates); return; }
  apiFetch('GET', '/api/objects/templates').then(function(d) {
    _objectTemplates = d.templates || [];
    renderObjTplGrid(_objectTemplates);
  });
}

function renderObjTplGrid(templates, typeFilter) {
  var grid = document.getElementById('obj-tpl-grid');
  if (!grid) return;
  var filtered = typeFilter && typeFilter !== 'all'
    ? templates.filter(function(t){ return t.type === typeFilter; })
    : templates;
  if (!filtered.length) {
    grid.innerHTML = '<div style="color:#7f8c8d">No templates in this category.</div>';
    return;
  }
  grid.innerHTML = filtered.map(function(t) {
    var icon = t.icon ? '<i class="fas ' + _esc(t.icon) + ' me-1"></i>' : '&#9657;';
    var typeColor = {domain:'#e67e22', event_trigger:'#e74c3c',
                     materialized_view:'#8e44ad', view:'#2980b9', policy:'#27ae60'}[t.type] || '#888';
    var objId = 'objcard-' + _esc(t.key || '');
    return '<div class="tpl-card" id="' + objId + '" onclick="selectObjTemplate(\'' + _esc(t.key || '') + '\')" ' +
      'style="border-left:3px solid ' + typeColor + '">' +
      '<h6>' + icon + ' ' + _esc(t.label) + '</h6>' +
      '<p>' + _esc(t.description || '') + '</p>' +
      '<span style="font-size:.68em;color:' + typeColor + '">' + _esc(t.type) + '</span>' +
      '</div>';
  }).join('');
}

function filterObjType(typeVal) {
  document.querySelectorAll('.obj-tcat').forEach(function(b){
    b.classList.toggle('active', b.dataset.type === typeVal);
  });
  renderObjTplGrid(_objectTemplates || [], typeVal);
}

function selectObjTemplate(templateKey) {
  _selectedObjTplKey = templateKey;
  document.querySelectorAll('.tpl-card[id^="objcard-"]').forEach(function(c){
    c.classList.toggle('selected', c.id === 'objcard-' + templateKey);
  });
  var tmpl = (_objectTemplates || []).find(function(t){ return t.key === templateKey; });
  if (!tmpl) return;

  document.getElementById('obj-tpl-params-title').textContent = tmpl.label;
  document.getElementById('obj-tpl-params-desc').textContent  = tmpl.description || '';
  document.getElementById('obj-tpl-sql-preview').textContent  = '';

  var fields = document.getElementById('obj-tpl-params-fields');
  fields.innerHTML = (tmpl.params || []).map(function(p) {
    var dflt = (tmpl.defaults || {})[p] || '';
    if (p === 'table') {
      var sel = cy.$('node[type="table"]:selected');
      if (sel.length === 1) dflt = sel[0].id();
    }
    return '<div><label style="font-size:.75em;color:#7f8c8d">' + _esc(p) + '</label>' +
      '<input id="obj-param-' + _esc(p) + '" class="form-control input-sm" ' +
      'style="background:#253545;color:#ecf0f1;border-color:#445566" value="' + _esc(dflt) + '"></div>';
  }).join('');

  document.getElementById('obj-tpl-params-form').style.display = '';
  document.getElementById('obj-tpl-apply-btn').onclick = function() { applyObjectTemplate(); };
}

function _getObjTplParams() {
  var tmpl = (_objectTemplates || []).find(function(t){ return t.key === _selectedObjTplKey; });
  if (!tmpl) return null;
  var params = { template_key: _selectedObjTplKey };
  (tmpl.params || []).forEach(function(p) {
    var el = document.getElementById('obj-param-' + p);
    if (el) params[p] = el.value.trim();
  });
  return params;
}

function previewObjectTemplate() {
  var tmpl = (_objectTemplates || []).find(function(t){ return t.key === _selectedObjTplKey; });
  var params = _getObjTplParams();
  if (!tmpl || !params) return;
  var sql = tmpl.sql || '';
  Object.keys(params).forEach(function(k) {
    sql = sql.split('{' + k + '}').join(params[k]);
  });
  document.getElementById('obj-tpl-sql-preview').textContent = sql || '(no preview)';
}

function applyObjectTemplate() {
  var params = _getObjTplParams();
  if (!params) return;
  setStatus('Applying object template…');
  apiFetch('POST', '/api/objects/apply-template', params).then(function(d) {
    if (d.errors && d.errors.length) {
      setStatus('✗ Error: ' + d.errors[0]);
    } else {
      setStatus('✓ Applied: ' + _selectedObjTplKey);
      document.getElementById('obj-tpl-params-form').style.display = 'none';
    }
  });
}

/* ── Domains ───────────────────────────────────────────────────────────────── */
function loadDomains() {
  var schema = (document.getElementById('dom-schema') || {}).value || 'public';
  var list   = document.getElementById('domains-list');
  if (list) list.innerHTML = '<div style="color:#7f8c8d">Loading…</div>';
  apiFetch('GET', '/api/domains/list?schema=' + encodeURIComponent(schema)).then(function(d) {
    var rows = d.domains || [];
    if (!list) return;
    if (!rows.length) { list.innerHTML = '<div style="color:#7f8c8d">No domains found.</div>'; return; }
    list.innerHTML = rows.map(function(r) {
      return '<div class="trigger-row">' +
        '<span><b>' + _esc(r.domain_name) + '</b> : <i>' + _esc(r.data_type || '') + '</i>' +
        (r.check_clause ? ' <small style="color:#7f8c8d">CHECK (' + _esc(r.check_clause) + ')</small>' : '') + '</span>' +
        '<button class="btn btn-xs btn-danger" onclick="dropDomain(' + JSON.stringify(r.domain_name) + ')">Drop</button>' +
        '</div>';
    }).join('');
  });
}

function dropDomain(name) {
  if (!confirm('Drop domain "' + name + '"?')) return;
  var schema = (document.getElementById('dom-schema') || {}).value || 'public';
  apiFetch('POST', '/api/domains/drop', {name: name, schema: schema}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Dropped domain: ' + name);
    loadDomains();
  });
}

/* ── Event Triggers ────────────────────────────────────────────────────────── */
function loadEventTriggers() {
  var list = document.getElementById('evtrig-list');
  if (list) list.innerHTML = '<div style="color:#7f8c8d">Loading…</div>';
  apiFetch('GET', '/api/event-triggers/list').then(function(d) {
    var rows = d.event_triggers || [];
    if (!list) return;
    if (!rows.length) { list.innerHTML = '<div style="color:#7f8c8d">No event triggers found.</div>'; return; }
    list.innerHTML = rows.map(function(r) {
      var en = r.enabled !== 'D';
      return '<div class="trigger-row">' +
        '<span><b>' + _esc(r.name) + '</b> ON <i>' + _esc(r.event) + '</i>' +
        ' → ' + _esc(r.function_name || '') + '</span>' +
        '<div style="display:flex;gap:4px">' +
        '<button class="btn btn-xs btn-' + (en ? 'warning' : 'success') + '" onclick="toggleEvTrig(' +
          JSON.stringify(r.name) + ',' + (!en) + ')">' + (en ? 'Disable' : 'Enable') + '</button>' +
        '<button class="btn btn-xs btn-danger" onclick="dropEvTrig(' + JSON.stringify(r.name) + ')">Drop</button>' +
        '</div></div>';
    }).join('');
  });
}

function toggleEvTrig(name, enable) {
  apiFetch('POST', '/api/event-triggers/toggle', {name: name, enable: enable}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Event trigger ' + (enable ? 'enabled' : 'disabled'));
    loadEventTriggers();
  });
}

function dropEvTrig(name) {
  if (!confirm('Drop event trigger "' + name + '"?')) return;
  apiFetch('POST', '/api/event-triggers/drop', {name: name}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Dropped: ' + name);
    loadEventTriggers();
  });
}

/* ── Materialized Views ────────────────────────────────────────────────────── */
function loadMatViews() {
  var schema = (document.getElementById('mv-schema') || {}).value || 'public';
  var list   = document.getElementById('matviews-list');
  if (list) list.innerHTML = '<div style="color:#7f8c8d">Loading…</div>';
  apiFetch('GET', '/api/matviews/list?schema=' + encodeURIComponent(schema)).then(function(d) {
    var rows = d.mat_views || [];
    if (!list) return;
    if (!rows.length) { list.innerHTML = '<div style="color:#7f8c8d">No materialized views found.</div>'; return; }
    list.innerHTML = rows.map(function(r) {
      var pop = r.ispopulated ? '<span style="color:#2ecc71">&#9679; populated</span>' : '<span style="color:#e74c3c">&#9675; empty</span>';
      return '<div class="trigger-row">' +
        '<span onclick="loadMatViewDef(\'' + _esc(r.view_name) + '\')" style="cursor:pointer">' +
        '<b>' + _esc(r.view_name) + '</b> ' + pop + (r.size ? ' <small style="color:#7f8c8d">' + _esc(r.size) + '</small>' : '') + '</span>' +
        '<div style="display:flex;gap:4px">' +
        '<button class="btn btn-xs btn-info" onclick="refreshMatView(\'' + _esc(r.view_name) + '\')">&#8635; Refresh</button>' +
        '<button class="btn btn-xs btn-danger" onclick="dropMatView(\'' + _esc(r.view_name) + '\')">Drop</button>' +
        '</div></div>';
    }).join('');
  });
}

function loadMatViewDef(name) {
  var schema = (document.getElementById('mv-schema') || {}).value || 'public';
  apiFetch('GET', '/api/views/definition?name=' + encodeURIComponent(name) + '&schema=' + encodeURIComponent(schema) + '&materialized=1')
    .then(function(d) {
      document.getElementById('matview-def-name').textContent = name;
      document.getElementById('matview-def-sql').textContent  = d.definition || '';
      document.getElementById('matview-def').style.display = '';
    });
}

function refreshMatView(name) {
  var schema = (document.getElementById('mv-schema') || {}).value || 'public';
  setStatus('Refreshing ' + name + '…');
  apiFetch('POST', '/api/matviews/refresh', {name: name, schema: schema, concurrently: true}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Refreshed: ' + name);
  });
}

function dropMatView(name) {
  if (!confirm('Drop materialized view "' + name + '"?')) return;
  var schema = (document.getElementById('mv-schema') || {}).value || 'public';
  apiFetch('POST', '/api/matviews/drop', {name: name, schema: schema}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Dropped: ' + name);
    loadMatViews();
  });
}

function showViewEditor(materialized) {
  var ed = document.getElementById('view-editor');
  if (ed) {
    ed.style.display = '';
    var cb = document.getElementById('view-edit-mat');
    if (cb) cb.checked = !!materialized;
  }
}

function submitCustomView() {
  var name = (document.getElementById('view-edit-name') || {}).value || '';
  var sql  = (document.getElementById('view-edit-sql')  || {}).value || '';
  var mat  = document.getElementById('view-edit-mat') && document.getElementById('view-edit-mat').checked;
  var schema = (document.getElementById(mat ? 'mv-schema' : 'view-schema') || {}).value || 'public';
  if (!name || !sql) { alert('Name and SQL required.'); return; }
  apiFetch('POST', '/api/views/create', {name: name, query: sql, schema: schema, materialized: mat}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ ' + (mat ? 'Materialized view' : 'View') + ' created: ' + name);
    if (!d.errors || !d.errors.length) {
      document.getElementById('view-editor').style.display = 'none';
      mat ? loadMatViews() : loadViews();
    }
  });
}

/* ── Views ─────────────────────────────────────────────────────────────────── */
function loadViews() {
  var schema = (document.getElementById('view-schema') || {}).value || 'public';
  var list   = document.getElementById('views-list');
  if (list) list.innerHTML = '<div style="color:#7f8c8d">Loading…</div>';
  apiFetch('GET', '/api/views/list?schema=' + encodeURIComponent(schema)).then(function(d) {
    var rows = d.views || [];
    if (!list) return;
    if (!rows.length) { list.innerHTML = '<div style="color:#7f8c8d">No views found.</div>'; return; }
    list.innerHTML = rows.map(function(r) {
      return '<div class="fn-row" onclick="loadViewDef(\'' + _esc(r.view_name) + '\')">' +
        '<b>' + _esc(r.view_name) + '</b>' +
        '<button class="btn btn-xs btn-danger" onclick="event.stopPropagation();dropView(\'' + _esc(r.view_name) + '\')">Drop</button>' +
        '</div>';
    }).join('');
  });
}

function loadViewDef(name) {
  var schema = (document.getElementById('view-schema') || {}).value || 'public';
  apiFetch('GET', '/api/views/definition?name=' + encodeURIComponent(name) + '&schema=' + encodeURIComponent(schema))
    .then(function(d) {
      document.getElementById('view-edit-name').value = name;
      document.getElementById('view-edit-sql').value  = d.definition || '';
      document.getElementById('view-editor').style.display = '';
    });
}

function dropView(name) {
  if (!confirm('Drop view "' + name + '"?')) return;
  var schema = (document.getElementById('view-schema') || {}).value || 'public';
  apiFetch('POST', '/api/views/drop', {name: name, schema: schema}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Dropped view: ' + name);
    loadViews();
  });
}

/* ── Policies ──────────────────────────────────────────────────────────────── */
function loadPolicies() {
  var table  = (document.getElementById('pol-table') || {}).value || '';
  var qs     = table ? '?table=' + encodeURIComponent(table) : '';
  var list   = document.getElementById('policies-list');
  if (list) list.innerHTML = '<div style="color:#7f8c8d">Loading…</div>';
  apiFetch('GET', '/api/policies/list' + qs).then(function(d) {
    var rows = d.policies || [];
    if (!list) return;
    if (!rows.length) { list.innerHTML = '<div style="color:#7f8c8d">No policies found.</div>'; return; }
    list.innerHTML = rows.map(function(r) {
      return '<div class="trigger-row">' +
        '<span><b>' + _esc(r.policyname) + '</b> on <i>' + _esc(r.tablename) + '</i>' +
        ' FOR <b>' + _esc(r.cmd || 'ALL') + '</b></span>' +
        '<button class="btn btn-xs btn-danger" onclick="dropPolicy(\'' + _esc(r.tablename) + '\',\'' + _esc(r.policyname) + '\')">Drop</button>' +
        '</div>';
    }).join('');
  });
}

function dropPolicy(table, name) {
  if (!confirm('Drop policy "' + name + '" on "' + table + '"?')) return;
  apiFetch('POST', '/api/policies/drop', {table: table, name: name}).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Dropped policy: ' + name);
    loadPolicies();
  });
}

/* ── Reverse engineer: reload canvas from live DB ─────────────────────────── */
function reverseEngineerFromDB() {
  if (cy.elements().length > 0) {
    if (!confirm('Replace the current canvas with the live database schema?')) return;
  }
  setStatus('Reverse engineering from live database…');
  apiFetch('POST', '/api/reverse-engineer').then(function(data) {
    if (data.error) { setStatus('✗ Reverse engineer error: ' + data.error); return; }
    var elements = data.elements || [];
    cy.elements().remove();
    if (elements.length) {
      cy.add(elements);
      var layoutName = (window.cytoscapeFcose && cy.nodes().length > 20) ? 'fcose' : 'cose';
      cy.layout({
        name: layoutName,
        animate: cy.nodes().length < 60,
        animationDuration: 400,
        nodeRepulsion: 8000,
        idealEdgeLength: 80,
        quality: 'default',
        randomize: false,
      }).run();
    }
    setStatus('✓ Loaded ' + cy.nodes('[type="table"]').length + ' tables from live database');
  }).catch(function(err) {
    setStatus('✗ Reverse engineer failed: ' + (err && err.message ? err.message : String(err)));
  });
}

function submitCustomPolicy() {
  var payload = {
    table:      (document.getElementById('pol-tbl')   || {}).value || '',
    name:       (document.getElementById('pol-name')  || {}).value || '',
    command:    (document.getElementById('pol-cmd')   || {}).value || 'ALL',
    using_expr: (document.getElementById('pol-using') || {}).value || '',
    check_expr: (document.getElementById('pol-check') || {}).value || null,
    schema:     'public',
  };
  if (!payload.table || !payload.name || !payload.using_expr) {
    alert('Table, name, and USING expression are required.');
    return;
  }
  apiFetch('POST', '/api/policies/create', payload).then(function(d) {
    setStatus(d.errors && d.errors.length ? '✗ ' + d.errors[0] : '✓ Policy created: ' + payload.name);
    if (!d.errors || !d.errors.length) loadPolicies();
  });
}
