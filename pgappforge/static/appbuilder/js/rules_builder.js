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
		'  <input type="text" class="form-control cond-field" placeholder="field name"/>' +
		'</div>' +
		'<div class="col-xs-2">' +
		'  <select class="form-control cond-op">' + opOptions + '</select>' +
		'</div>' +
		'<div class="col-xs-4">' +
		'  <input type="text" class="form-control cond-value" placeholder="value"/>' +
		'</div>' +
		'<div class="col-xs-2">' +
		'  <select class="form-control cond-logic">' +
		'    <option value="AND">AND</option>' +
		'    <option value="OR">OR</option>' +
		'  </select>' +
		'</div>' +
		'<div class="col-xs-1">' +
		'  <button type="button" class="btn btn-xs btn-danger"' +
		'    onclick="$(\'#cond-row-' + idx + '\').remove()">' +
		'    <i class="fa fa-minus"></i>' +
		'  </button>' +
		'</div>' +
		'</div>';

	$("#conditions-container").append(html);
}


function _collectConditions() {
	var conditions = [];
	$("#conditions-container .condition-row").each(function() {
		var field = $(this).find(".cond-field").val().trim();
		if (!field) return;
		conditions.push({
			field:  field,
			op:     $(this).find(".cond-op").val(),
			value:  $(this).find(".cond-value").val(),
			logic:  $(this).find(".cond-logic").val()
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
		'    onchange="updateActionParams(' + idx + ', this.value)">' +
		'    <option value="set_field">set_field</option>' +
		'    <option value="block">block</option>' +
		'    <option value="send_email">send_email</option>' +
		'    <option value="call_webhook">call_webhook</option>' +
		'  </select>' +
		'</div>' +
		'<div class="col-xs-7 action-params" id="action-params-' + idx + '">' +
		  _actionParamsHtml("set_field", idx) +
		'</div>' +
		'<div class="col-xs-1">' +
		'  <button type="button" class="btn btn-xs btn-danger"' +
		'    onclick="$(\'#action-row-' + idx + '\').remove()">' +
		'    <i class="fa fa-minus"></i>' +
		'  </button>' +
		'</div>' +
		'</div>';

	$("#actions-container").append(html);
}


function _actionParamsHtml(type, idx) {
	if (type === "set_field") {
		return '<div class="row">' +
			'<div class="col-xs-6">' +
			'  <input type="text" class="form-control ap-field"' +
			'    placeholder="field name"/>' +
			'</div>' +
			'<div class="col-xs-6">' +
			'  <input type="text" class="form-control ap-value"' +
			'    placeholder="new value"/>' +
			'</div></div>';
	} else if (type === "block") {
		return '<input type="text" class="form-control ap-message"' +
			' placeholder="Error message shown to user"/>';
	} else if (type === "send_email") {
		return '<div class="row">' +
			'<div class="col-xs-4">' +
			'  <input type="text" class="form-control ap-to" placeholder="to"/>' +
			'</div>' +
			'<div class="col-xs-4">' +
			'  <input type="text" class="form-control ap-subject" placeholder="subject"/>' +
			'</div>' +
			'<div class="col-xs-4">' +
			'  <input type="text" class="form-control ap-body" placeholder="body"/>' +
			'</div></div>';
	} else if (type === "call_webhook") {
		return '<div class="row">' +
			'<div class="col-xs-8">' +
			'  <input type="text" class="form-control ap-url"' +
			'    placeholder="https://..."/>' +
			'</div>' +
			'<div class="col-xs-4">' +
			'  <input type="text" class="form-control ap-payload"' +
			'    placeholder=\'{"key":"value"}\'/>' +
			'</div></div>';
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
		}
		actions.push(action);
	});
	return actions;
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
				var idx = row.attr("id").replace("action-row-", "");
				row.find(".action-type").val(a.type);
				updateActionParams(idx, a.type);
				if (a.type === "set_field") {
					row.find(".ap-field").val(a.field || "");
					row.find(".ap-value").val(a.value || "");
				} else if (a.type === "block") {
					row.find(".ap-message").val(a.message || "");
				} else if (a.type === "send_email") {
					row.find(".ap-to").val(a.to || "");
					row.find(".ap-subject").val(a.subject || "");
					row.find(".ap-body").val(a.body || "");
				} else if (a.type === "call_webhook") {
					row.find(".ap-url").val(a.url || "");
					row.find(".ap-payload").val(JSON.stringify(a.payload || {}));
				}
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
	var id         = $("#ruleset-id").val();
	var name       = $("#ruleset-name").val().trim();
	var modelName  = $("#ruleset-model").val().trim();
	var desc       = $("#ruleset-description").val().trim();
	var priority   = parseInt($("#ruleset-priority").val()) || 100;
	var ruleName   = $("#rule-name").val().trim();
	var trigger    = $("#rule-trigger").val();
	var conditions = _collectConditions();
	var actions    = _collectActions();

	if (!name) { alert("RuleSet name is required."); return; }
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
		// Update existing ruleset
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
		// Create new ruleset
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
 * Test / dry-run
 * ------------------------------------------------------------------------- */

function testRule() {
	var id = $("#ruleset-id").val();
	if (!id) {
		alert("Save the ruleset first before testing.");
		return;
	}
	var conditions = _collectConditions();
	// Build a synthetic record from condition fields
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
			record:     record
		}),
		success: function(data) {
			var html = "<strong>Test results for: " + data.ruleset + "</strong><ul>";
			(data.results || []).forEach(function(r) {
				var icon = r.matched ? "✓" : "✗";
				html += "<li>" + icon + " <em>" + r.rule_name + "</em>";
				if (r.matched && r.actions_triggered.length) {
					html += " → " + r.actions_triggered.map(function(a) {
						return a.type;
					}).join(", ");
				}
				html += "</li>";
			});
			html += "</ul>";
			$("#test-result-area").html(html).show();
		},
		error: function(xhr) {
			$("#test-result-area")
				.html("<strong>Error:</strong> " +
					(xhr.responseJSON && xhr.responseJSON.error || xhr.statusText))
				.show();
		}
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
