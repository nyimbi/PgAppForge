/**
 * ERP Islands Runtime
 * PgAppForge v4.8
 *
 * Lazy-loads CDN libraries on demand and mounts registered island components
 * after the DOM is ready. No global Date.now() calls — timestamps are
 * server-provided via Jinja2 context.
 */
;(function (global) {
  'use strict';

  /* ── CDN library registry ─────────────────────────────────────────── */
  var CDN = {
    alpine:   'https://cdn.jsdelivr.net/npm/alpinejs@3.14.0/dist/cdn.min.js',
    chartjs:  'https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js',
    sortable: 'https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js',
    d3:       'https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js'
  };

  /* ── In-flight / resolved promise cache ──────────────────────────── */
  var _loaded  = {};   /* name → true when script is in DOM + executed */
  var _pending = {};   /* name → Promise<void> while loading            */

  /**
   * loadLib(name) → Promise<void>
   * Injects a <script> tag for the named CDN library exactly once.
   * Subsequent calls for the same name return the cached promise.
   */
  function loadLib(name) {
    if (_loaded[name])  return Promise.resolve();
    if (_pending[name]) return _pending[name];

    var url = CDN[name];
    if (!url) {
      return Promise.reject(new Error('ERP Islands: unknown lib "' + name + '"'));
    }

    _pending[name] = new Promise(function (resolve, reject) {
      var script   = document.createElement('script');
      script.src   = url;
      script.async = true;

      script.onload = function () {
        _loaded[name] = true;
        delete _pending[name];
        resolve();
      };

      script.onerror = function () {
        delete _pending[name];
        reject(new Error('ERP Islands: failed to load lib "' + name + '" from ' + url));
      };

      document.head.appendChild(script);
    });

    return _pending[name];
  }

  /* ── Island registry ──────────────────────────────────────────────── */
  var _registry = {};  /* name → { libs: string[], fn: Function } */

  /**
   * ERPIslands.register(name, libs, fn)
   *
   * @param {string}   name  - Island identifier (matches data-island attribute)
   * @param {string[]} libs  - CDN library names to load before calling fn
   * @param {Function} fn    - Factory: receives (element, libs) and wires the island
   */
  function register(name, libs, fn) {
    if (typeof fn !== 'function') {
      console.warn('ERP Islands: register("' + name + '") — fn must be a function');
      return;
    }
    _registry[name] = { libs: libs || [], fn: fn };
  }

  /**
   * ERPIslands.mount(el)
   * Mounts a single island element (must have data-island attribute).
   */
  function mount(el) {
    var name = el.getAttribute('data-island');
    if (!name) return;

    var def = _registry[name];
    if (!def) {
      console.warn('ERP Islands: no island registered for "' + name + '"');
      return;
    }

    /* Mark as mounting to avoid double-init on dynamic content */
    if (el.dataset.islandMounted === 'true') return;
    el.dataset.islandMounted = 'true';

    /* Show skeleton while libs load */
    el.setAttribute('aria-busy', 'true');

    var libPromises = def.libs.map(function (lib) { return loadLib(lib); });

    Promise.all(libPromises)
      .then(function () {
        try {
          def.fn(el);
        } catch (e) {
          console.error('ERP Islands: error mounting "' + name + '"', e);
          _renderError(el, e);
        }
      })
      .catch(function (e) {
        console.error('ERP Islands: failed to load libs for "' + name + '"', e);
        _renderError(el, e);
      })
      .finally(function () {
        el.removeAttribute('aria-busy');
      });
  }

  /**
   * ERPIslands.mountAll()
   * Finds every [data-island] element in the document and mounts it.
   * Safe to call multiple times — already-mounted islands are skipped.
   */
  function mountAll() {
    var islands = document.querySelectorAll('[data-island]');
    islands.forEach(function (el) { mount(el); });
  }

  /* ── Internal helpers ─────────────────────────────────────────────── */
  function _renderError(el, err) {
    el.innerHTML =
      '<div style="padding:12px;color:#e02424;font-size:12px;border:1px solid #fde8e8;border-radius:6px;background:#fff5f5">' +
      '<strong>Island failed to mount:</strong> ' + (err && err.message ? _esc(err.message) : 'unknown error') +
      '</div>';
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;');
  }

  /* ── JSON fetch helper (available globally) ───────────────────────── */
  /**
   * ERPIslands.fetchJSON(url, options) → Promise<any>
   * Thin wrapper around fetch that parses JSON and rejects on HTTP errors.
   */
  function fetchJSON(url, options) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, options || {}))
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status + ' ' + res.statusText);
        return res.json();
      });
  }

  /* ── Public API ───────────────────────────────────────────────────── */
  global.ERPIslands = {
    register:  register,
    mount:     mount,
    mountAll:  mountAll,
    loadLib:   loadLib,
    fetchJSON: fetchJSON,
    CDN:       CDN
  };

  /* ── Auto-mount on DOM ready ──────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(); });
  } else {
    /* DOMContentLoaded already fired (script loaded async/deferred) */
    mountAll();
  }

}(window));
