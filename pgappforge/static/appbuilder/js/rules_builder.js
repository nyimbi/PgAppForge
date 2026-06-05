/**
 * rules_builder.js
 * Vanilla JS / jQuery helpers for the Rules Engine Builder UI.
 *
 * Assumes jQuery is already loaded (provided by FAB).
 * All API calls target /rules/api/* endpoints served by RulesBuilderView.
 */

/* -------------------------------------------------------------------------
 * Condition rows
 * ------------------------------------------------------------------------- */

var _conditionCount = 0;
var _validateDebounceTimer = null;

function addConditionRow() {
  _conditionCount++;
  var idx = _conditionCount;
  var ops = ["=", "!=", ">", "<", ">=", "<=", "contains", "in",
             "is_null", "is_not_null", "starts_with"];
  var opOptions = ops.map(function(o) {
    return '<option value="' + o + '">' + o + '</option>';
  }).join("");

  var html = '<div class="row condition-row" id="cond-row-' + idx + '">' +
    '<div class="col-xs-3">' +
    '  <input type="text" class="form-control cond-field"' +
    '    placeholder="field name"' +
    '    oninput="scheduleValidate()"/>' +
    '</div>' +
    '<div class="col-xs-2">' +
    '  <select class="form-control cond-op" onchange="scheduleValidate()">' +
    opOptions +
    '  </select>' +
    '</div>' +
    '<div class="col-xs-4">' +
    '  <div class="input-group">' +
    '    <input type="text" class="form-control cond-value"' +
    '      placeholder="value" oninput="scheduleValidate()"/>' +
    '    <span class="input-group-btn">' +
    '      <button type="button" class="btn btn-default btn-value-helper"' +
    '        title="Prefix with $ for field reference, {{ for template"' +
    '        onclick="cycleValuePrefix(this)">' +
    '        <i class="fa fa-magic"></i>' +
    '      </button>' +
    '    </span>' +
    '  </div>' +
    '</div>' +
    '<div class="col-xs-2">' +
    '  <select class="form-control cond-logic" onchange="scheduleValidate()">' +
    '    <option value="AND">AND</option>' +
    '    <option value="OR">OR</option>' +
    '  </select>' +
    '</div>' +
    '<div class="col-xs-1">' +
    '  <button type="button" class="btn btn-xs btn-danger"' +
    '    onclick="$(\'#cond-row-' + idx + '\').remove(); scheduleValidate()">' +
    '    <i class="fa fa-minus"></i>' +
    '  </button>' +
    '</div>' +
    '</div>';

  $("#conditions-container").append(html);
}

/**
 * Cycle a condition value input through plain → $field → {{field}} prefix modes.
 * The "ƒ" button lives inside an input-group next to the value input.
 */
function cycleValuePrefix(btn) {
  var input = $(btn).closest(".input-group").find(".cond-value");
  var val = input.val();
  if (val.startsWith("{{")) {
    // {{field}} → strip template braces
    input.val(val.replace(/^\{\{|\}\}$/g, "").trim());
  } else if (val.startsWith("$")) {
    // $field → wrap as {{field}}
    input.val("{{" + val.slice(1) + "}}");
  } else {
    // plain → prepend $
    input.val("$" + val);
  }
  scheduleValidate();
}


function _collectConditions() {
  var conditions = [];
  $("#conditions-container .condition-row").each(function() {
    var field = $(this).find(".cond-field").val().trim();
    if (!field) return;
    conditions.push({
      field: field,
      op:    $(this).find(".cond-op").val(),
      value: $(this).find(".cond-value").val(),
      logic: $(this).find(".cond-logic").val()
    });
  });
  return conditions;
}


/* -------------------------------------------------------------------------
 * Action rows
 * ------------------------------------------------------------------------- */

var _actionCount = 0;

function addActionRow() {
  _actionCount++;
  var idx = _actionCount;

  var html = '<div class="row action-row" id="action-row-' + idx + '">' +
    '<div class="col-xs-3">' +
    '  <select class="form-control action-type"' +
    '    onchange="updateActionParams(' + idx + ', this.value); scheduleValidate()">' +
    '    <option value="set_field">set_field</option>' +
    '    <option value="block">block</option>' +
    '    <option value="add_error">add_error</option>' +
    '    <option value="send_email">send_email</option>' +
    '    <option value="call_webhook">call_webhook</option>' +
    '    <option value="create_record">create_record</option>' +
    '    <option value="start_workflow">start_workflow</option>' +
    '  </select>' +
    '</div>' +
    '<div class="col-xs-7 action-params" id="action-params-' + idx + '">' +
      _actionParamsHtml("set_field", idx) +
    '</div>' +
    '<div class="col-xs-1">' +
    '  <button type="button" class="btn btn-xs btn-danger"' +
    '    onclick="$(\'#action-row-' + idx + '\').remove(); scheduleValidate()">' +
    '    <i class="fa fa-minus"></i>' +
    '  </button>' +
    '</div>' +
    '</div>';

  $("#actions-container").append(html);
}


function _actionParamsHtml(type, idx) {
  var change = 'oninput="scheduleValidate()" onchange="scheduleValidate()"';
  if (type === "set_field") {
    return '<div class="row">' +
      '<div class="col-xs-6">' +
      '  <input type="text" class="form-control ap-field"' +
      '    placeholder="field name" ' + change + '/>' +
      '</div>' +
      '<div class="col-xs-6">' +
      '  <input type="text" class="form-control ap-value"' +
      '    placeholder="new value" ' + change + '/>' +
      '</div></div>';

  } else if (type === "block") {
    return '<input type="text" class="form-control ap-message"' +
      ' placeholder="Error message shown to user" ' + change + '/>';

  } else if (type === "add_error") {
    return '<div class="row">' +
      '<div class="col-xs-4">' +
      '  <input type="text" class="form-control ap-field"' +
      '    placeholder="field name" ' + change + '/>' +
      '</div>' +
      '<div class="col-xs-8">' +
      '  <input type="text" class="form-control ap-message"' +
      '    placeholder="Validation error message" ' + change + '/>' +
      '</div></div>';

  } else if (type === "send_email") {
    return '<div class="row">' +
      '<div class="col-xs-4">' +
      '  <input type="text" class="form-control ap-to" placeholder="to" ' + change + '/>' +
      '</div>' +
      '<div class="col-xs-4">' +
      '  <input type="text" class="form-control ap-subject" placeholder="subject" ' + change + '/>' +
      '</div>' +
      '<div class="col-xs-4">' +
      '  <input type="text" class="form-control ap-body" placeholder="body" ' + change + '/>' +
      '</div></div>';

  } else if (type === "call_webhook") {
    return '<div class="row">' +
      '<div class="col-xs-8">' +
      '  <input type="text" class="form-control ap-url"' +
      '    placeholder="https://..." ' + change + '/>' +
      '</div>' +
      '<div class="col-xs-4">' +
      '  <input type="text" class="form-control ap-payload"' +
      '    placeholder=\'{"key":"value"}\' ' + change + '/>' +
      '</div></div>';

  } else if (type === "create_record") {
    return '<div class="row">' +
      '<div class="col-xs-4">' +
      '  <input type="text" class="form-control ap-model"' +
      '    placeholder="ModelName" ' + change + '/>' +
      '</div>' +
      '<div class="col-xs-8">' +
      '  <input type="text" class="form-control ap-fields-json"' +
      '    placeholder=\'{"field": "value"}\' ' + change + '/>' +
      '</div></div>';

  } else if (type === "start_workflow") {
    return '<input type="text" class="form-control ap-workflow-type"' +
      ' placeholder="workflow_type (e.g. approval)" ' + change + '/>';
  }
  return "";
}


function updateActionParams(idx, type) {
  $("#action-params-" + idx).html(_actionParamsHtml(type, idx));
}


function _collectActions() {
  var actions = [];
  $("#actions-container .action-row").each(function() {
    var type = $(this).find(".action-type").val();
    var action = {type: type};

    if (type === "set_field") {
      action.field = $(this).find(".ap-field").val().trim();
      action.value = $(this).find(".ap-value").val();
    } else if (type === "block") {
      action.message = $(this).find(".ap-message").val().trim();
    } else if (type === "add_error") {
      action.field   = $(this).find(".ap-field").val().trim();
      action.message = $(this).find(".ap-message").val().trim();
    } else if (type === "send_email") {
      action.to      = $(this).find(".ap-to").val().trim();
      action.subject = $(this).find(".ap-subject").val().trim();
      action.body    = $(this).find(".ap-body").val().trim();
    } else if (type === "call_webhook") {
      action.url = $(this).find(".ap-url").val().trim();
      try {
        action.payload = JSON.parse($(this).find(".ap-payload").val() || "{}");
      } catch (e) {
        action.payload = {};
      }
    } else if (type === "create_record") {
      action.model = $(this).find(".ap-model").val().trim();
      try {
        action.fields = JSON.parse($(this).find(".ap-fields-json").val() || "{}");
      } catch (e) {
        action.fields = {};
      }
    } else if (type === "start_workflow") {
      action.workflow_type = $(this).find(".ap-workflow-type").val().trim();
    }
    actions.push(action);
  });
  return actions;
}


/* -------------------------------------------------------------------------
 * Populate action row from loaded data (handles new types)
 * ------------------------------------------------------------------------- */

function _populateActionRow(row, a) {
  var idx = row.attr("id").replace("action-row-", "");
  row.find(".action-type").val(a.type);
  updateActionParams(idx, a.type);

  if (a.type === "set_field") {
    row.find(".ap-field").val(a.field || "");
    row.find(".ap-value").val(a.value || "");
  } else if (a.type === "block") {
    row.find(".ap-message").val(a.message || "");
  } else if (a.type === "add_error") {
    row.find(".ap-field").val(a.field || "");
    row.find(".ap-message").val(a.message || "");
  } else if (a.type === "send_email") {
    row.find(".ap-to").val(a.to || "");
    row.find(".ap-subject").val(a.subject || "");
    row.find(".ap-body").val(a.body || "");
  } else if (a.type === "call_webhook") {
    row.find(".ap-url").val(a.url || "");
    row.find(".ap-payload").val(JSON.stringify(a.payload || {}));
  } else if (a.type === "create_record") {
    row.find(".ap-model").val(a.model || "");
    row.find(".ap-fields-json").val(JSON.stringify(a.fields || {}));
  } else if (a.type === "start_workflow") {
    row.find(".ap-workflow-type").val(a.workflow_type || "");
  }
}


/* -------------------------------------------------------------------------
 * RuleSet form helpers
 * ------------------------------------------------------------------------- */

function clearRulesetForm() {
  $("#ruleset-id").val("");
  $("#ruleset-name").val("");
  $("#ruleset-model").val("");
  $("#ruleset-description").val("");
  $("#ruleset-priority").val("100");
  $("#rule-name").val("");
  $("#rule-trigger").val("on_create");
  $("#conditions-container").empty();
  $("#actions-container").empty();
  $("#rulesetModalTitle").text("New RuleSet");
  $("#test-result-area").hide();
  $("#validator-results").html(
    '<p class="text-muted"><i class="fa fa-info-circle"></i> ' +
    'Click Validate to check your conditions and actions.</p>'
  );
  $("#modal-visualizer-diagram").html(
    '<p class="text-muted"><i class="fa fa-info-circle"></i> ' +
    'Save the ruleset first, then click this tab to render the flowchart.</p>'
  );
  // Switch back to designer tab
  $("#modal-tabs a[href='#tab-designer']").tab("show");
  _conditionCount = 0;
  _actionCount = 0;
}


function populateRulesetForm(id) {
  $.getJSON("/rules/api/rulesets/" + id, function(data) {
    clearRulesetForm();
    $("#ruleset-id").val(data.id);
    $("#ruleset-name").val(data.name);
    $("#ruleset-model").val(data.model_name);
    $("#ruleset-description").val(data.description || "");
    $("#ruleset-priority").val(data.priority);
    $("#rulesetModalTitle").text("Edit RuleSet: " + data.name);

    // Load first rule for editing if present
    if (data.rules && data.rules.length > 0) {
      var r = data.rules[0];
      $("#rule-name").val(r.name);
      $("#rule-trigger").val(r.trigger_event);
      (r.conditions_json || []).forEach(function(c) {
        addConditionRow();
        var row = $("#conditions-container .condition-row:last");
        row.find(".cond-field").val(c.field || "");
        row.find(".cond-op").val(c.op || "=");
        row.find(".cond-value").val(c.value || "");
        row.find(".cond-logic").val(c.logic || "AND");
      });
      (r.actions_json || []).forEach(function(a) {
        addActionRow();
        var row = $("#actions-container .action-row:last");
        _populateActionRow(row, a);
      });
    }

    $("#rulesetModal").modal("show");
  }).fail(function() {
    alert("Failed to load ruleset " + id);
  });
}


/* -------------------------------------------------------------------------
 * Save
 * ------------------------------------------------------------------------- */

function saveRuleset() {
  var id        = $("#ruleset-id").val();
  var name      = $("#ruleset-name").val().trim();
  var modelName = $("#ruleset-model").val().trim();
  var desc      = $("#ruleset-description").val().trim();
  var priority  = parseInt($("#ruleset-priority").val()) || 100;
  var ruleName  = $("#rule-name").val().trim();
  var trigger   = $("#rule-trigger").val();
  var conditions = _collectConditions();
  var actions    = _collectActions();

  if (!name)      { alert("RuleSet name is required."); return; }
  if (!modelName) { alert("Model name is required."); return; }

  var rulesetPayload = {
    name:        name,
    model_name:  modelName,
    description: desc,
    priority:    priority
  };

  function saveRule(rulesetId) {
    if (!ruleName) return;
    $.ajax({
      url:         "/rules/api/rules",
      method:      "POST",
      contentType: "application/json",
      data: JSON.stringify({
        ruleset_id:      rulesetId,
        name:            ruleName,
        trigger_event:   trigger,
        conditions_json: conditions,
        actions_json:    actions
      }),
      success: function() {
        $("#rulesetModal").modal("hide");
        location.reload();
      },
      error: function(xhr) {
        alert("Rule save error: " + (xhr.responseJSON && xhr.responseJSON.error || xhr.statusText));
      }
    });
  }

  if (id) {
    $.ajax({
      url:         "/rules/api/rulesets/" + id,
      method:      "PUT",
      contentType: "application/json",
      data:        JSON.stringify(rulesetPayload),
      success: function() {
        if (ruleName) {
          saveRule(parseInt(id));
        } else {
          $("#rulesetModal").modal("hide");
          location.reload();
        }
      },
      error: function(xhr) {
        alert("Save error: " + (xhr.responseJSON && xhr.responseJSON.error || xhr.statusText));
      }
    });
  } else {
    $.ajax({
      url:         "/rules/api/rulesets",
      method:      "POST",
      contentType: "application/json",
      data:        JSON.stringify(rulesetPayload),
      success: function(data) {
        saveRule(data.id);
      },
      error: function(xhr) {
        alert("Create error: " + (xhr.responseJSON && xhr.responseJSON.error || xhr.statusText));
      }
    });
  }
}


/* -------------------------------------------------------------------------
 * Validate — calls /rules/api/validate
 * ------------------------------------------------------------------------- */

/**
 * Schedule a debounced validate call (500 ms after last change).
 */
function scheduleValidate() {
  if (_validateDebounceTimer) clearTimeout(_validateDebounceTimer);
  _validateDebounceTimer = setTimeout(function() {
    validateRule(true); // silent = don't switch tabs
  }, 500);
}

/**
 * Full validation call. When silent=true we only update the badge count
 * without switching to the validator tab.
 */
function validateRule(silent) {
  var conditions = _collectConditions();
  var actions    = _collectActions();

  $("#validate-spinner").show();

  $.ajax({
    url:         "/rules/api/validate",
    method:      "POST",
    contentType: "application/json",
    data: JSON.stringify({
      conditions_json: conditions,
      actions_json:    actions
    }),
    success: function(data) {
      $("#validate-spinner").hide();
      _renderValidatorResults(data, conditions, actions);
      if (!silent) {
        $("#modal-tabs a[href='#tab-validator']").tab("show");
      }
    },
    error: function(xhr) {
      $("#validate-spinner").hide();
      var msg = (xhr.responseJSON && xhr.responseJSON.error) || xhr.statusText;
      $("#validator-results").html(
        '<div class="alert alert-danger"><i class="fa fa-times-circle"></i> ' +
        'Validate error: ' + _esc(msg) + '</div>'
      );
    }
  });
}

function _renderValidatorResults(data, conditions, actions) {
  var errors = data.errors || [];

  // Build lookup: path → messages
  var byPath = {};
  errors.forEach(function(e) {
    if (!byPath[e.path]) byPath[e.path] = [];
    byPath[e.path].push(e.message);
  });

  var html = "";

  // Summary banner
  if (data.valid) {
    html += '<div class="alert alert-success">' +
      '<i class="fa fa-check-circle"></i> <strong>Valid</strong> — ' +
      'all conditions and actions pass structural checks.' +
      '</div>';
  } else {
    html += '<div class="alert alert-danger">' +
      '<i class="fa fa-times-circle"></i> <strong>' + errors.length + ' error(s)</strong>' +
      '</div>';
  }

  // Conditions table
  if (conditions.length > 0) {
    html += '<h6><i class="fa fa-filter"></i> Conditions</h6>';
    html += '<table class="table table-condensed table-bordered"><thead>' +
      '<tr><th>#</th><th>Field</th><th>Op</th><th>Value</th><th>Status</th></tr>' +
      '</thead><tbody>';
    conditions.forEach(function(c, i) {
      var pathErrors = byPath["conditions[" + i + "]"] || [];
      ["field", "op", "value"].forEach(function(f) {
        var fe = byPath["conditions[" + i + "]." + f];
        if (fe) pathErrors = pathErrors.concat(fe);
      });
      var statusCell = pathErrors.length === 0
        ? '<span class="label label-success"><i class="fa fa-check"></i> OK</span>'
        : '<span class="label label-danger"><i class="fa fa-times"></i> ' +
          pathErrors.map(_esc).join("; ") + '</span>';
      html += '<tr>' +
        '<td>' + (i + 1) + '</td>' +
        '<td><code>' + _esc(c.field) + '</code></td>' +
        '<td><code>' + _esc(c.op) + '</code></td>' +
        '<td><code>' + _esc(String(c.value)) + '</code></td>' +
        '<td>' + statusCell + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
  }

  // Actions table
  if (actions.length > 0) {
    html += '<h6><i class="fa fa-bolt"></i> Actions</h6>';
    html += '<table class="table table-condensed table-bordered"><thead>' +
      '<tr><th>#</th><th>Type</th><th>Params</th><th>Status</th></tr>' +
      '</thead><tbody>';
    actions.forEach(function(a, i) {
      var pathErrors = byPath["actions[" + i + "]"] || [];
      ["type", "field", "message", "url", "model", "workflow_type"].forEach(function(f) {
        var fe = byPath["actions[" + i + "]." + f];
        if (fe) pathErrors = pathErrors.concat(fe);
      });
      var statusCell = pathErrors.length === 0
        ? '<span class="label label-success"><i class="fa fa-check"></i> OK</span>'
        : '<span class="label label-danger"><i class="fa fa-times"></i> ' +
          pathErrors.map(_esc).join("; ") + '</span>';
      var params = Object.keys(a)
        .filter(function(k) { return k !== "type"; })
        .map(function(k) { return _esc(k) + "=" + _esc(String(a[k])); })
        .join(", ");
      html += '<tr>' +
        '<td>' + (i + 1) + '</td>' +
        '<td><span class="label label-info">' + _esc(a.type) + '</span></td>' +
        '<td><small>' + params + '</small></td>' +
        '<td>' + statusCell + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
  }

  if (conditions.length === 0 && actions.length === 0) {
    html += '<p class="text-muted">No conditions or actions defined yet.</p>';
  }

  $("#validator-results").html(html);

  // Update tab label with error count badge
  var tabLink = $("#modal-tabs a[href='#tab-validator']");
  tabLink.find(".badge").remove();
  if (!data.valid) {
    tabLink.append(' <span class="badge" style="background:#d9534f">' + errors.length + '</span>');
  }
}


/* -------------------------------------------------------------------------
 * Test / dry-run — uses evaluate_dry() result
 * ------------------------------------------------------------------------- */

function testRule() {
  var id = $("#ruleset-id").val();
  if (!id) {
    alert("Save the ruleset first before testing.");
    return;
  }
  var conditions = _collectConditions();
  var event      = $("#rule-trigger").val() || "on_create";

  // Build a synthetic record from condition field/value pairs
  var record = {};
  conditions.forEach(function(c) {
    if (c.field) record[c.field] = c.value;
  });

  $.ajax({
    url:         "/rules/api/test",
    method:      "POST",
    contentType: "application/json",
    data: JSON.stringify({
      ruleset_id: parseInt(id),
      event:      event,
      record:     record
    }),
    success: function(data) {
      _renderDryRunResult(data);
      $("#test-result-area").show();
    },
    error: function(xhr) {
      $("#test-result-area")
        .html('<div class="alert alert-danger"><i class="fa fa-times-circle"></i> <strong>Error:</strong> ' +
          _esc((xhr.responseJSON && xhr.responseJSON.error) || xhr.statusText) +
          '</div>')
        .show();
    }
  });
}

function _renderDryRunResult(data) {
  var dr = data.dry_run || {};
  var matched = dr.rules_matched || [];

  var blockBadge = dr.would_block
    ? '<span class="badge badge-block"><i class="fa fa-ban"></i> BLOCK</span>'
    : '<span class="badge badge-ok"><i class="fa fa-check"></i> PASS</span>';

  var html = '<strong><i class="fa fa-play-circle"></i> Dry-run: ' +
    _esc(data.ruleset) + '</strong>' + blockBadge + '<hr/>';

  html += '<table class="table table-condensed">' +
    '<tbody>' +
    '<tr><td>Rules matched</td><td>' +
    (matched.length ? matched.map(_esc).join(", ") : '<em>none</em>') +
    '</td></tr>';

  if (dr.would_block) {
    html += '<tr class="danger"><td>Block reason</td><td>' +
      (dr.block_field ? '<code>' + _esc(dr.block_field) + '</code>: ' : '') +
      _esc(dr.block_message) + '</td></tr>';
  }

  var setFields = dr.would_set || {};
  var setKeys = Object.keys(setFields);
  if (setKeys.length) {
    html += '<tr><td>Would set</td><td>';
    html += setKeys.map(function(k) {
      return '<code>' + _esc(k) + '</code> = ' + _esc(String(setFields[k]));
    }).join(", ");
    html += '</td></tr>';
  }

  var emails = dr.would_send_emails || [];
  if (emails.length) {
    html += '<tr><td>Would send emails</td><td>';
    html += emails.map(function(e) {
      return 'to: <code>' + _esc(e.to || "") + '</code>';
    }).join(", ");
    html += '</td></tr>';
  }

  var webhooks = dr.would_call_webhooks || [];
  if (webhooks.length) {
    html += '<tr><td>Would call webhooks</td><td>';
    html += webhooks.map(function(w) {
      return '<code>' + _esc(w.url || "") + '</code>';
    }).join(", ");
    html += '</td></tr>';
  }

  var creates = dr.would_create_records || [];
  if (creates.length) {
    html += '<tr><td>Would create records</td><td>';
    html += creates.map(function(c) {
      return '<code>' + _esc(c.model || "") + '</code>';
    }).join(", ");
    html += '</td></tr>';
  }

  var workflows = dr.would_start_workflows || [];
  if (workflows.length) {
    html += '<tr><td>Would start workflows</td><td>';
    html += workflows.map(function(w) {
      return '<code>' + _esc(w.workflow_type || "") + '</code>';
    }).join(", ");
    html += '</td></tr>';
  }

  html += '</tbody></table>';

  $("#test-result-area").html(html);
}


/* -------------------------------------------------------------------------
 * Visualize — calls /rules/api/visualize/<id> and renders Mermaid
 * ------------------------------------------------------------------------- */

/**
 * Called from the main table "Viz" button — renders into the page-level panel.
 */
function visualizeRuleset(id) {
  var $panel   = $("#visualizer-panel");
  var $diagram = $("#visualizer-diagram");
  $diagram.html('<i class="fa fa-spinner fa-spin"></i> Loading…');
  $panel.show();
  $("html, body").animate({scrollTop: $panel.offset().top - 80}, 300);

  _fetchAndRenderMermaid(id, $diagram);
}

/**
 * Called from the modal Visualizer tab — renders inside the modal.
 */
function visualizeCurrentRuleset() {
  var id = $("#ruleset-id").val();
  var $diagram = $("#modal-visualizer-diagram");

  if (!id) {
    $diagram.html(
      '<p class="text-muted"><i class="fa fa-info-circle"></i> ' +
      'Save the ruleset first.</p>'
    );
    return;
  }
  $diagram.html('<i class="fa fa-spinner fa-spin"></i> Loading…');
  _fetchAndRenderMermaid(parseInt(id), $diagram);
}

function _fetchAndRenderMermaid(id, $target) {
  $.getJSON("/rules/api/visualize/" + id, function(data) {
    var def = data.mermaid || "";
    if (!def) {
      $target.html('<p class="text-muted">No rules to visualize.</p>');
      return;
    }
    // Use mermaid.render() API (Mermaid 10+)
    var uniqueId = "mermaid-" + id + "-" + Date.now();
    try {
      mermaid.render(uniqueId, def).then(function(result) {
        $target.html(result.svg);
      }).catch(function(err) {
        $target.html(
          '<div class="alert alert-warning"><i class="fa fa-exclamation-triangle"></i> ' +
          'Render error: ' + _esc(String(err)) + '</div>' +
          '<pre>' + _esc(def) + '</pre>'
        );
      });
    } catch (e) {
      // Fallback: show raw source if mermaid is not available
      $target.html('<pre>' + _esc(def) + '</pre>');
    }
  }).fail(function(xhr) {
    $target.html(
      '<div class="alert alert-danger">Failed to load diagram: ' +
      _esc((xhr.responseJSON && xhr.responseJSON.error) || xhr.statusText) +
      '</div>'
    );
  });
}


/* -------------------------------------------------------------------------
 * Toggle enabled
 * ------------------------------------------------------------------------- */

function toggleRuleset(id, enabled) {
  $.ajax({
    url:         "/rules/api/rulesets/" + id,
    method:      "PUT",
    contentType: "application/json",
    data:        JSON.stringify({enabled: enabled}),
    success: function() { location.reload(); },
    error:   function(xhr) {
      alert("Toggle error: " + (xhr.responseJSON && xhr.responseJSON.error || xhr.statusText));
    }
  });
}


/* -------------------------------------------------------------------------
 * Delete
 * ------------------------------------------------------------------------- */

function deleteRuleset(id) {
  if (!confirm("Delete ruleset " + id + " and all its rules?")) return;
  $.ajax({
    url:     "/rules/api/rulesets/" + id,
    method:  "DELETE",
    success: function() { location.reload(); },
    error:   function(xhr) {
      alert("Delete error: " + (xhr.responseJSON && xhr.responseJSON.error || xhr.statusText));
    }
  });
}


/* -------------------------------------------------------------------------
 * Export
 * ------------------------------------------------------------------------- */

function exportRuleset(id) {
  window.location.href = "/rules/api/export/" + id;
}


/* -------------------------------------------------------------------------
 * Import
 * ------------------------------------------------------------------------- */

function importRuleset() {
  $("#importModal").modal("show");
}

function doImport() {
  var raw = $("#import-json").val().trim();
  if (!raw) { alert("Paste JSON first."); return; }
  var payload;
  try {
    payload = JSON.parse(raw);
  } catch (e) {
    alert("Invalid JSON: " + e.message);
    return;
  }
  $.ajax({
    url:         "/rules/api/import",
    method:      "POST",
    contentType: "application/json",
    data:        JSON.stringify(payload),
    success: function() {
      $("#importModal").modal("hide");
      location.reload();
    },
    error: function(xhr) {
      alert("Import error: " + (xhr.responseJSON && xhr.responseJSON.error || xhr.statusText));
    }
  });
}


/* -------------------------------------------------------------------------
 * Utility
 * ------------------------------------------------------------------------- */

function _esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
