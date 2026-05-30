"""
Wallet Widgets for PgAppForge

This module provides specialized widgets for the wallet system,
including financial input widgets, charts, and dashboard components.
"""

import json
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union

from flask import render_template_string, url_for
from pgappforge.widgets import FormWidget, ListWidget, ShowWidget
from pgappforge.security import current_user
from markupsafe import Markup

from .models import UserWallet, WalletTransaction, WalletBudget
from .services import AnalyticsService, CurrencyService

log = logging.getLogger(__name__)


class CurrencyInputWidget(FormWidget):
    """
    Currency input widget with currency selector and formatting.
    
    Provides a professional currency input with real-time formatting,
    currency conversion, and validation.
    """
    
    template = '''
    <div class="currency-input-widget" data-field="{{ field.name }}">
        <div class="input-group">
            <div class="input-group-prepend">
                <select class="form-control currency-selector" 
                        name="{{ field.name }}_currency"
                        style="max-width: 100px;">
                    {% for currency in currencies %}
                    <option value="{{ currency }}" 
                            {% if currency == default_currency %}selected{% endif %}>
                        {{ currency }}
                    </option>
                    {% endfor %}
                </select>
            </div>
            {{ field(class="form-control currency-amount", 
                     placeholder="0.00", 
                     **kwargs) }}
            <div class="input-group-append">
                <span class="input-group-text">
                    <i class="fa fa-calculator currency-converter" 
                       title="Currency Converter" 
                       style="cursor: pointer;"></i>
                </span>
            </div>
        </div>
        
        {% if show_conversion %}
        <div class="conversion-display mt-2" style="font-size: 0.875rem; color: #6c757d;">
            <span class="converted-amount"></span>
        </div>
        {% endif %}
        
        {% if validation_rules %}
        <div class="validation-feedback"></div>
        {% endif %}
    </div>
    
    <script>
    $(document).ready(function() {
        const widget = $('.currency-input-widget[data-field="{{ field.name }}"]');
        const amountInput = widget.find('.currency-amount');
        const currencySelect = widget.find('.currency-selector');
        const conversionDisplay = widget.find('.converted-amount');
        
        // Format currency input
        amountInput.on('input', function() {
            let value = $(this).val();
            
            // Remove non-numeric characters except decimal point
            value = value.replace(/[^0-9.]/g, '');
            
            // Ensure only one decimal point
            const parts = value.split('.');
            if (parts.length > 2) {
                value = parts[0] + '.' + parts.slice(1).join('');
            }
            
            // Limit decimal places to 2
            if (parts.length === 2 && parts[1].length > 2) {
                value = parts[0] + '.' + parts[1].substring(0, 2);
            }
            
            $(this).val(value);
            
            {% if show_conversion %}
            updateConversion();
            {% endif %}
        });
        
        // Currency change handler
        currencySelect.on('change', function() {
            {% if show_conversion %}
            updateConversion();
            {% endif %}
        });
        
        {% if show_conversion %}
        function updateConversion() {
            const amount = parseFloat(amountInput.val()) || 0;
            const fromCurrency = currencySelect.val();
            const toCurrency = '{{ conversion_currency }}';
            
            if (amount > 0 && fromCurrency !== toCurrency) {
                // Make API call to get conversion
                $.ajax({
                    url: '/wallet/api/convert',
                    method: 'GET',
                    data: {
                        amount: amount,
                        from: fromCurrency,
                        to: toCurrency
                    },
                    success: function(data) {
                        conversionDisplay.text(
                            `≈ ${data.converted_amount} ${toCurrency} (Rate: ${data.rate})`
                        );
                    }
                });
            } else {
                conversionDisplay.text('');
            }
        }
        {% endif %}
        
        // Validation
        {% if validation_rules %}
        amountInput.on('blur', function() {
            validateAmount();
        });
        
        function validateAmount() {
            const amount = parseFloat(amountInput.val()) || 0;
            let isValid = true;
            let message = '';
            
            {% for rule in validation_rules %}
            {% if rule.type == 'min_value' %}
            if (amount < {{ rule.value }}) {
                isValid = false;
                message = 'Amount must be at least {{ rule.value }}';
            }
            {% elif rule.type == 'max_value' %}
            if (amount > {{ rule.value }}) {
                isValid = false;
                message = 'Amount cannot exceed {{ rule.value }}';
            }
            {% endif %}
            {% endfor %}
            
            const feedback = widget.find('.validation-feedback');
            if (isValid) {
                amountInput.removeClass('is-invalid').addClass('is-valid');
                feedback.removeClass('invalid-feedback').addClass('valid-feedback').text('✓ Valid amount');
            } else {
                amountInput.removeClass('is-valid').addClass('is-invalid');
                feedback.removeClass('valid-feedback').addClass('invalid-feedback').text(message);
            }
        }
        {% endif %}
        
        // Currency converter modal
        widget.find('.currency-converter').on('click', function() {
            // Open currency converter modal (implementation depends on UI framework)
            showCurrencyConverterModal();
        });
    });
    </script>
    '''
    
    def __init__(self, currencies: List[str] = None, default_currency: str = 'USD',
                 show_conversion: bool = True, conversion_currency: str = 'USD',
                 validation_rules: List[Dict] = None, **kwargs):
        super().__init__(**kwargs)
        self.currencies = currencies or CurrencyService.get_supported_currencies()
        self.default_currency = default_currency
        self.show_conversion = show_conversion
        self.conversion_currency = conversion_currency
        self.validation_rules = validation_rules or []
    
    def __call__(self, field, **kwargs):
        return Markup(render_template_string(
            self.template,
            field=field,
            currencies=self.currencies,
            default_currency=self.default_currency,
            show_conversion=self.show_conversion,
            conversion_currency=self.conversion_currency,
            validation_rules=self.validation_rules,
            **kwargs
        ))


class TransactionFormWidget(FormWidget):
    """
    Enhanced transaction form widget with smart defaults and validation.
    
    Provides intelligent form behavior with category suggestions,
    amount formatting, and real-time validation.
    """
    
    template = '''
    <div class="transaction-form-widget">
        <div class="row">
            <div class="col-md-6">
                <div class="form-group">
                    <label for="wallet_id">Wallet</label>
                    <select name="wallet_id" class="form-control" required>
                        <option value="">Select Wallet</option>
                        {% for wallet in wallets %}
                        <option value="{{ wallet.id }}" 
                                data-currency="{{ wallet.currency_code }}"
                                data-balance="{{ wallet.balance }}">
                            {{ wallet.wallet_name }} 
                            ({{ wallet.balance }} {{ wallet.currency_code }})
                        </option>
                        {% endfor %}
                    </select>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="form-group">
                    <label for="transaction_type">Type</label>
                    <select name="transaction_type" class="form-control" required>
                        {% for type_value, type_label in transaction_types %}
                        <option value="{{ type_value }}">{{ type_label }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <div class="form-group">
                    <label for="amount">Amount</label>
                    <div class="input-group">
                        <div class="input-group-prepend">
                            <span class="input-group-text currency-symbol">$</span>
                        </div>
                        <input type="number" name="amount" class="form-control" 
                               step="0.01" min="0" required
                               placeholder="0.00">
                    </div>
                    <div class="balance-info mt-1" style="font-size: 0.875rem; color: #6c757d;">
                        <span class="available-balance"></span>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="form-group">
                    <label for="category_id">Category</label>
                    <select name="category_id" class="form-control category-select">
                        <option value="">Select Category</option>
                        {% for category in categories %}
                        <option value="{{ category.id }}" 
                                data-type="{{ category.category_type }}">
                            {{ category.full_name }}
                        </option>
                        {% endfor %}
                    </select>
                </div>
            </div>
        </div>
        
        <div class="form-group">
            <label for="description">Description</label>
            <input type="text" name="description" class="form-control"
                   placeholder="Transaction description">
            <div class="suggested-descriptions mt-1">
                <!-- Dynamic suggestions will appear here -->
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <div class="form-group">
                    <label for="payment_method_id">Payment Method</label>
                    <select name="payment_method_id" class="form-control">
                        <option value="">Select Payment Method</option>
                        {% for method in payment_methods %}
                        <option value="{{ method.id }}">
                            {{ method.name }} ({{ method.method_type }})
                        </option>
                        {% endfor %}
                    </select>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="form-group">
                    <label for="reference_number">Reference Number</label>
                    <input type="text" name="reference_number" class="form-control"
                           placeholder="Optional reference number">
                </div>
            </div>
        </div>
        
        <div class="form-actions">
            <button type="submit" class="btn btn-primary">
                <i class="fa fa-plus"></i> Add Transaction
            </button>
            <button type="button" class="btn btn-secondary" onclick="clearForm()">
                <i class="fa fa-refresh"></i> Clear
            </button>
        </div>
    </div>
    
    <script>
    $(document).ready(function() {
        const walletSelect = $('select[name="wallet_id"]');
        const typeSelect = $('select[name="transaction_type"]');
        const amountInput = $('input[name="amount"]');
        const categorySelect = $('select[name="category_id"]');
        const descriptionInput = $('input[name="description"]');
        
        // Wallet change handler
        walletSelect.on('change', function() {
            const selectedOption = $(this).find('option:selected');
            const currency = selectedOption.data('currency') || '$';
            const balance = selectedOption.data('balance') || 0;
            
            $('.currency-symbol').text(currency);
            $('.available-balance').text(`Available: ${balance} ${currency}`);
        });
        
        // Transaction type change handler
        typeSelect.on('change', function() {
            const type = $(this).val();
            
            // Filter categories by type
            categorySelect.find('option').each(function() {
                const categoryType = $(this).data('type');
                if (!categoryType || categoryType === type || type === 'transfer') {
                    $(this).show();
                } else {
                    $(this).hide();
                }
            });
            
            // Update form styling based on type
            if (type === 'expense') {
                amountInput.removeClass('border-success').addClass('border-danger');
            } else if (type === 'income') {
                amountInput.removeClass('border-danger').addClass('border-success');
            } else {
                amountInput.removeClass('border-danger border-success');
            }
        });
        
        // Amount validation
        amountInput.on('input', function() {
            const amount = parseFloat($(this).val()) || 0;
            const type = typeSelect.val();
            const selectedWallet = walletSelect.find('option:selected');
            const balance = parseFloat(selectedWallet.data('balance')) || 0;
            
            if (type === 'expense' && amount > balance) {
                $(this).addClass('is-invalid');
                $('.balance-info').append('<div class="text-danger">Insufficient funds</div>');
            } else {
                $(this).removeClass('is-invalid');
                $('.balance-info .text-danger').remove();
            }
        });
        
        // Description suggestions
        descriptionInput.on('focus', function() {
            loadDescriptionSuggestions();
        });
        
        function loadDescriptionSuggestions() {
            const category = categorySelect.val();
            if (category) {
                $.ajax({
                    url: '/wallet/api/description-suggestions',
                    method: 'GET',
                    data: { category_id: category },
                    success: function(data) {
                        displaySuggestions(data.suggestions);
                    }
                });
            }
        }
        
        function displaySuggestions(suggestions) {
            const container = $('.suggested-descriptions');
            container.empty();
            
            if (suggestions.length > 0) {
                const suggestionsList = $('<div class="suggestion-pills"></div>');
                suggestions.forEach(function(suggestion) {
                    suggestionsList.append(
                        `<span class="badge badge-light suggestion-pill" 
                               style="cursor: pointer; margin: 2px;">
                            ${suggestion}
                        </span>`
                    );
                });
                container.append(suggestionsList);
                
                // Handle suggestion clicks
                container.find('.suggestion-pill').on('click', function() {
                    descriptionInput.val($(this).text());
                    container.empty();
                });
            }
        }
        
        // Initialize
        walletSelect.trigger('change');
        typeSelect.trigger('change');
    });
    
    function clearForm() {
        $('.transaction-form-widget form')[0].reset();
        $('.currency-symbol').text('$');
        $('.available-balance').text('');
        $('.suggested-descriptions').empty();
    }
    </script>
    '''
    
    def __init__(self, wallets: List = None, categories: List = None,
                 payment_methods: List = None, transaction_types: List = None, **kwargs):
        super().__init__(**kwargs)
        self.wallets = wallets or []
        self.categories = categories or []
        self.payment_methods = payment_methods or []
        self.transaction_types = transaction_types or []
    
    def __call__(self, **kwargs):
        return Markup(render_template_string(
            self.template,
            wallets=self.wallets,
            categories=self.categories,
            payment_methods=self.payment_methods,
            transaction_types=self.transaction_types,
            **kwargs
        ))


class BudgetProgressWidget(ShowWidget):
    """
    Budget progress widget with visual progress indicators and alerts.
    
    Displays budget progress with color-coded alerts, spending trends,
    and projected completion dates.
    """
    
    template = '''
    <div class="budget-progress-widget">
        {% for budget in budgets %}
        <div class="budget-card mb-3" data-budget-id="{{ budget.budget_id }}">
            <div class="card">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="card-title mb-0">{{ budget.budget_name }}</h6>
                        <span class="badge badge-{% if budget.alert_level >= 3 %}danger{% elif budget.alert_level >= 2 %}warning{% elif budget.alert_level >= 1 %}info{% else %}success{% endif %}">
                            {{ "%.1f"|format(budget.spent_percentage) }}%
                        </span>
                    </div>
                    
                    <div class="progress mb-2" style="height: 8px;">
                        <div class="progress-bar 
                                    {% if budget.alert_level >= 3 %}bg-danger{% elif budget.alert_level >= 2 %}bg-warning{% elif budget.alert_level >= 1 %}bg-info{% else %}bg-success{% endif %}"
                             role="progressbar" 
                             style="width: {{ budget.spent_percentage }}%"
                             aria-valuenow="{{ budget.spent_percentage }}" 
                             aria-valuemin="0" 
                             aria-valuemax="100">
                        </div>
                    </div>
                    
                    <div class="row small text-muted">
                        <div class="col-6">
                            <strong>${{ budget.spent_amount }}</strong> spent
                        </div>
                        <div class="col-6 text-right">
                            <strong>${{ budget.remaining_amount }}</strong> remaining
                        </div>
                    </div>
                    
                    <div class="row small text-muted mt-1">
                        <div class="col-6">
                            Budget: ${{ budget.budget_amount }}
                        </div>
                        <div class="col-6 text-right">
                            {{ budget.days_remaining }} days left
                        </div>
                    </div>
                    
                    {% if budget.alert_level >= 2 %}
                    <div class="alert alert-{% if budget.alert_level >= 3 %}danger{% else %}warning{% endif %} mt-2 py-1 px-2">
                        <small>
                            {% if budget.alert_level >= 3 %}
                            <i class="fa fa-exclamation-triangle"></i> Budget exceeded!
                            {% else %}
                            <i class="fa fa-warning"></i> Approaching budget limit
                            {% endif %}
                        </small>
                    </div>
                    {% endif %}
                    
                    <div class="budget-actions mt-2">
                        <button class="btn btn-sm btn-outline-primary" 
                                onclick="showBudgetDetails({{ budget.budget_id }})">
                            <i class="fa fa-chart-line"></i> Details
                        </button>
                        {% if not budget.is_on_track %}
                        <button class="btn btn-sm btn-outline-warning"
                                onclick="showBudgetTips({{ budget.budget_id }})">
                            <i class="fa fa-lightbulb"></i> Tips
                        </button>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
        
        {% if not budgets %}
        <div class="text-center text-muted py-4">
            <i class="fa fa-chart-pie fa-2x mb-3"></i>
            <p>No active budgets found.</p>
            <a href="/budgetview/add" class="btn btn-primary btn-sm">
                <i class="fa fa-plus"></i> Create Budget
            </a>
        </div>
        {% endif %}
    </div>
    
    <script>
    function showBudgetDetails(budgetId) {
        // Load budget details modal
        $.ajax({
            url: `/wallet/api/budget/${budgetId}/details`,
            method: 'GET',
            success: function(data) {
                showModal('Budget Details', renderBudgetDetails(data));
            }
        });
    }
    
    function showBudgetTips(budgetId) {
        // Show budget optimization tips
        const tips = [
            'Track daily spending to stay within budget',
            'Consider reducing discretionary expenses',
            'Set up spending alerts for better control',
            'Review and adjust budget if needed'
        ];
        
        let tipsHtml = '<ul>';
        tips.forEach(tip => {
            tipsHtml += `<li class="mb-2">${tip}</li>`;
        });
        tipsHtml += '</ul>';
        
        showModal('Budget Tips', tipsHtml);
    }
    
    function renderBudgetDetails(data) {
        return `
            <div class="budget-details">
                <div class="row mb-3">
                    <div class="col-md-6">
                        <canvas id="budgetChart" width="200" height="200"></canvas>
                    </div>
                    <div class="col-md-6">
                        <h6>Spending Analysis</h6>
                        <p><strong>Daily Average:</strong> $${data.daily_average}</p>
                        <p><strong>Projected Total:</strong> $${data.projected_spending}</p>
                        <p><strong>On Track:</strong> ${data.is_on_track ? 'Yes' : 'No'}</p>
                    </div>
                </div>
            </div>
        `;
    }
    
    function showModal(title, content) {
        // Implementation depends on your modal system
        console.log('Show modal:', title, content);
    }
    </script>
    '''
    
    def __init__(self, budgets: List = None, **kwargs):
        super().__init__(**kwargs)
        self.budgets = budgets or []
    
    def __call__(self, **kwargs):
        return Markup(render_template_string(
            self.template,
            budgets=self.budgets,
            **kwargs
        ))


class WalletBalanceWidget(ShowWidget):
    """
    Wallet balance widget with multiple wallet display and quick actions.
    
    Shows balance information with currency conversion, recent activity,
    and quick transaction buttons.
    """
    
    template = '''
    <div class="wallet-balance-widget">
        {% if wallets %}
        <div class="wallet-cards">
            {% for wallet in wallets %}
            <div class="wallet-card mb-3 {% if wallet.is_primary %}primary-wallet{% endif %}"
                 data-wallet-id="{{ wallet.id }}">
                <div class="card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <div>
                                <h6 class="card-title mb-1">
                                    {{ wallet.wallet_name }}
                                    {% if wallet.is_primary %}
                                    <span class="badge badge-primary badge-sm">Primary</span>
                                    {% endif %}
                                </h6>
                                <small class="text-muted">{{ wallet.wallet_type.title() }}</small>
                            </div>
                            <div class="wallet-actions">
                                <div class="dropdown">
                                    <button class="btn btn-sm btn-outline-secondary dropdown-toggle"
                                            type="button" data-toggle="dropdown">
                                        <i class="fa fa-cog"></i>
                                    </button>
                                    <div class="dropdown-menu">
                                        <a class="dropdown-item" href="/walletmodelview/edit/{{ wallet.id }}">
                                            <i class="fa fa-edit"></i> Edit Wallet
                                        </a>
                                        <a class="dropdown-item" href="/wallet/transaction/add?wallet_id={{ wallet.id }}">
                                            <i class="fa fa-plus"></i> Add Transaction
                                        </a>
                                        <div class="dropdown-divider"></div>
                                        <a class="dropdown-item text-warning" href="#" onclick="lockWallet({{ wallet.id }})">
                                            <i class="fa fa-lock"></i> Lock Wallet
                                        </a>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="balance-info">
                            <div class="balance-main">
                                <h4 class="mb-1 {% if wallet.balance < 0 %}text-danger{% endif %}">
                                    {{ wallet.balance }} {{ wallet.currency_code }}
                                </h4>
                                {% if show_conversion and wallet.currency_code != default_currency %}
                                <small class="text-muted">
                                    ≈ {{ wallet.balance_in_default_currency }} {{ default_currency }}
                                </small>
                                {% endif %}
                            </div>
                            
                            {% if wallet.available_balance != wallet.balance %}
                            <div class="available-balance mt-1">
                                <small class="text-muted">
                                    Available: {{ wallet.available_balance }} {{ wallet.currency_code }}
                                </small>
                            </div>
                            {% endif %}
                        </div>
                        
                        {% if wallet.last_transaction_date %}
                        <div class="last-activity mt-2">
                            <small class="text-muted">
                                Last activity: {{ wallet.last_transaction_date.strftime('%Y-%m-%d %H:%M') }}
                            </small>
                        </div>
                        {% endif %}
                        
                        <div class="quick-actions mt-3">
                            <button class="btn btn-sm btn-success mr-2" 
                                    onclick="quickTransaction({{ wallet.id }}, 'income')">
                                <i class="fa fa-plus"></i> Add Income
                            </button>
                            <button class="btn btn-sm btn-danger mr-2"
                                    onclick="quickTransaction({{ wallet.id }}, 'expense')">
                                <i class="fa fa-minus"></i> Add Expense
                            </button>
                            <button class="btn btn-sm btn-info"
                                    onclick="showTransferModal({{ wallet.id }})">
                                <i class="fa fa-exchange"></i> Transfer
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
        
        <div class="wallet-summary mt-4">
            <div class="card">
                <div class="card-body">
                    <h6 class="card-title">Total Portfolio</h6>
                    <div class="row">
                        <div class="col-md-4 text-center">
                            <h5 class="mb-1 text-success">{{ summary.total_income }}</h5>
                            <small class="text-muted">Total Income</small>
                        </div>
                        <div class="col-md-4 text-center">
                            <h5 class="mb-1 text-danger">{{ summary.total_expenses }}</h5>
                            <small class="text-muted">Total Expenses</small>
                        </div>
                        <div class="col-md-4 text-center">
                            <h5 class="mb-1 {% if summary.net_worth >= 0 %}text-success{% else %}text-danger{% endif %}">
                                {{ summary.net_worth }}
                            </h5>
                            <small class="text-muted">Net Worth</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        {% else %}
        <div class="text-center text-muted py-5">
            <i class="fa fa-wallet fa-3x mb-3"></i>
            <h5>No Wallets Found</h5>
            <p>Create your first wallet to get started with tracking your finances.</p>
            <a href="/walletmodelview/add" class="btn btn-primary">
                <i class="fa fa-plus"></i> Create Wallet
            </a>
        </div>
        {% endif %}
    </div>
    
    <script>
    function quickTransaction(walletId, type) {
        const modal = createQuickTransactionModal(walletId, type);
        $('body').append(modal);
        $('#quickTransactionModal').modal('show');
    }
    
    function createQuickTransactionModal(walletId, type) {
        const title = type === 'income' ? 'Add Income' : 'Add Expense';
        const color = type === 'income' ? 'success' : 'danger';
        
        return `
            <div class="modal fade" id="quickTransactionModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">${title}</h5>
                            <button type="button" class="close" data-dismiss="modal">
                                <span>&times;</span>
                            </button>
                        </div>
                        <form onsubmit="submitQuickTransaction(event)">
                            <div class="modal-body">
                                <input type="hidden" name="wallet_id" value="${walletId}">
                                <input type="hidden" name="transaction_type" value="${type}">
                                
                                <div class="form-group">
                                    <label>Amount</label>
                                    <input type="number" name="amount" class="form-control" 
                                           step="0.01" min="0" required placeholder="0.00">
                                </div>
                                
                                <div class="form-group">
                                    <label>Description</label>
                                    <input type="text" name="description" class="form-control"
                                           placeholder="Transaction description">
                                </div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-dismiss="modal">
                                    Cancel
                                </button>
                                <button type="submit" class="btn btn-${color}">
                                    <i class="fa fa-${type === 'income' ? 'plus' : 'minus'}"></i> 
                                    Add ${title}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        `;
    }
    
    function submitQuickTransaction(event) {
        event.preventDefault();
        
        const form = event.target;
        const formData = new FormData(form);
        
        $.ajax({
            url: '/wallet/quick-transaction',
            method: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function(response) {
                $('#quickTransactionModal').modal('hide');
                location.reload(); // Refresh to show updated balance
            },
            error: function(xhr) {
                alert('Error processing transaction: ' + xhr.responseText);
            }
        });
    }
    
    function showTransferModal(walletId) {
        // Implementation for transfer modal
        window.location.href = `/wallet/transaction/transfer?source=${walletId}`;
    }
    
    function lockWallet(walletId) {
        if (confirm('Are you sure you want to lock this wallet?')) {
            $.ajax({
                url: `/walletmodelview/action/`,
                method: 'POST',
                data: {
                    action: 'lock_wallet',
                    rowid: walletId
                },
                success: function() {
                    location.reload();
                },
                error: function(xhr) {
                    alert('Error locking wallet: ' + xhr.responseText);
                }
            });
        }
    }
    </script>
    '''
    
    def __init__(self, wallets: List = None, summary: Dict = None,
                 show_conversion: bool = True, default_currency: str = 'USD', **kwargs):
        super().__init__(**kwargs)
        self.wallets = wallets or []
        self.summary = summary or {}
        self.show_conversion = show_conversion
        self.default_currency = default_currency
    
    def __call__(self, **kwargs):
        return Markup(render_template_string(
            self.template,
            wallets=self.wallets,
            summary=self.summary,
            show_conversion=self.show_conversion,
            default_currency=self.default_currency,
            **kwargs
        ))


class ExpenseChartWidget(ShowWidget):
    """
    Expense chart widget with interactive charts and analytics.
    
    Displays spending patterns with various chart types,
    filtering options, and drill-down capabilities.
    """
    
    template = '''
    <div class="expense-chart-widget">
        <div class="chart-controls mb-3">
            <div class="row">
                <div class="col-md-3">
                    <select class="form-control form-control-sm" id="chartType">
                        <option value="pie">Pie Chart</option>
                        <option value="bar">Bar Chart</option>
                        <option value="line">Line Chart</option>
                        <option value="doughnut">Doughnut Chart</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <select class="form-control form-control-sm" id="timeRange">
                        <option value="7">Last 7 days</option>
                        <option value="30" selected>Last 30 days</option>
                        <option value="90">Last 90 days</option>
                        <option value="365">Last year</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <select class="form-control form-control-sm" id="groupBy">
                        <option value="category" selected>By Category</option>
                        <option value="day">By Day</option>
                        <option value="week">By Week</option>
                        <option value="payment_method">By Payment Method</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <button class="btn btn-sm btn-primary" onclick="refreshChart()">
                        <i class="fa fa-refresh"></i> Refresh
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="exportChart()">
                        <i class="fa fa-download"></i> Export
                    </button>
                </div>
            </div>
        </div>
        
        <div class="chart-container" style="position: relative; height: 400px;">
            <canvas id="expenseChart"></canvas>
        </div>
        
        <div class="chart-legend mt-3">
            <div class="row">
                <div class="col-md-8">
                    <div class="legend-items" id="chartLegend">
                        <!-- Dynamic legend items -->
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="chart-stats">
                        <div class="stat-item">
                            <span class="stat-label">Total Spending:</span>
                            <span class="stat-value" id="totalSpending">$0.00</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">Average per Day:</span>
                            <span class="stat-value" id="dailyAverage">$0.00</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">Largest Category:</span>
                            <span class="stat-value" id="largestCategory">-</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="chart-insights mt-3" id="chartInsights">
            <!-- AI-powered insights will appear here -->
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    let expenseChart;
    let currentData = {{ chart_data|tojson }};
    
    $(document).ready(function() {
        initializeChart();
        
        // Event handlers
        $('#chartType, #timeRange, #groupBy').on('change', refreshChart);
    });
    
    function initializeChart() {
        const ctx = document.getElementById('expenseChart').getContext('2d');
        const chartType = $('#chartType').val();
        
        const config = {
            type: chartType,
            data: {
                labels: Object.keys(currentData.grouped_data || {}),
                datasets: [{
                    label: 'Expenses',
                    data: Object.values(currentData.grouped_data || {}),
                    backgroundColor: generateColors(Object.keys(currentData.grouped_data || {}).length),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false // We'll create custom legend
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: $${context.parsed.toFixed(2)} (${percentage}%)`;
                            }
                        }
                    }
                },
                onClick: function(event, elements) {
                    if (elements.length > 0) {
                        const index = elements[0].index;
                        const label = this.data.labels[index];
                        drillDownCategory(label);
                    }
                }
            }
        };
        
        expenseChart = new Chart(ctx, config);
        updateStats();
        generateInsights();
    }
    
    function refreshChart() {
        const timeRange = $('#timeRange').val();
        const groupBy = $('#groupBy').val();
        const walletId = {{ wallet_id or 'null' }};
        
        $.ajax({
            url: '/wallet/analytics/api/spending',
            method: 'GET',
            data: {
                wallet_id: walletId,
                days: timeRange,
                group_by: groupBy
            },
            success: function(data) {
                currentData = data;
                updateChart();
                updateStats();
                generateInsights();
            },
            error: function(xhr) {
                console.error('Error loading chart data:', xhr.responseText);
            }
        });
    }
    
    function updateChart() {
        const chartType = $('#chartType').val();
        const labels = Object.keys(currentData.grouped_data || {});
        const data = Object.values(currentData.grouped_data || {});
        
        expenseChart.destroy();
        
        const ctx = document.getElementById('expenseChart').getContext('2d');
        const config = {
            type: chartType,
            data: {
                labels: labels,
                datasets: [{
                    label: 'Expenses',
                    data: data,
                    backgroundColor: generateColors(labels.length),
                    borderWidth: 1
                }]
            },
            options: expenseChart.options
        };
        
        expenseChart = new Chart(ctx, config);
    }
    
    function updateStats() {
        $('#totalSpending').text(`$${currentData.total_spent?.toFixed(2) || '0.00'}`);
        $('#dailyAverage').text(`$${currentData.daily_average?.toFixed(2) || '0.00'}`);
        
        // Find largest category
        const groupedData = currentData.grouped_data || {};
        const maxCategory = Object.keys(groupedData).reduce((a, b) => 
            groupedData[a] > groupedData[b] ? a : b, 
            Object.keys(groupedData)[0] || ''
        );
        $('#largestCategory').text(maxCategory || 'None');
        
        // Update custom legend
        updateLegend();
    }
    
    function updateLegend() {
        const legendContainer = $('#chartLegend');
        legendContainer.empty();
        
        const labels = Object.keys(currentData.grouped_data || {});
        const data = Object.values(currentData.grouped_data || {});
        const colors = generateColors(labels.length);
        
        labels.forEach((label, index) => {
            const percentage = ((data[index] / currentData.total_spent) * 100).toFixed(1);
            legendContainer.append(`
                <div class="legend-item mb-1">
                    <span class="legend-color" style="background-color: ${colors[index]}; 
                          display: inline-block; width: 12px; height: 12px; margin-right: 8px;"></span>
                    <span class="legend-label">${label}</span>
                    <span class="legend-value float-right">$${data[index].toFixed(2)} (${percentage}%)</span>
                </div>
            `);
        });
    }
    
    function generateColors(count) {
        const colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
            '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384'
        ];
        
        const result = [];
        for (let i = 0; i < count; i++) {
            result.push(colors[i % colors.length]);
        }
        return result;
    }
    
    function generateInsights() {
        const insights = [];
        const groupedData = currentData.grouped_data || {};
        
        // Generate spending insights
        if (currentData.daily_average > 50) {
            insights.push({
                type: 'warning',
                message: 'Your daily spending is above average. Consider reviewing your expenses.'
            });
        }
        
        const categories = Object.keys(groupedData);
        const maxCategory = categories.reduce((a, b) => 
            groupedData[a] > groupedData[b] ? a : b, 
            categories[0] || ''
        );
        
        if (maxCategory && groupedData[maxCategory] > currentData.total_spent * 0.4) {
            insights.push({
                type: 'info',
                message: `${maxCategory} accounts for a large portion of your spending. Review if this aligns with your budget.`
            });
        }
        
        // Display insights
        const insightsContainer = $('#chartInsights');
        insightsContainer.empty();
        
        insights.forEach(insight => {
            insightsContainer.append(`
                <div class="alert alert-${insight.type === 'warning' ? 'warning' : 'info'} py-2 px-3 mb-2">
                    <small><i class="fa fa-lightbulb"></i> ${insight.message}</small>
                </div>
            `);
        });
    }
    
    function drillDownCategory(category) {
        // Implement drill-down functionality
        console.log('Drill down into category:', category);
        // This could open a detailed view or filter transactions
    }
    
    function exportChart() {
        const link = document.createElement('a');
        link.download = 'expense-chart.png';
        link.href = expenseChart.toBase64Image();
        link.click();
    }
    </script>
    '''
    
    def __init__(self, chart_data: Dict = None, wallet_id: int = None, **kwargs):
        super().__init__(**kwargs)
        self.chart_data = chart_data or {}
        self.wallet_id = wallet_id
    
    def __call__(self, **kwargs):
        return Markup(render_template_string(
            self.template,
            chart_data=self.chart_data,
            wallet_id=self.wallet_id,
            **kwargs
        ))


__all__ = [
    'CurrencyInputWidget',
    'TransactionFormWidget',
    'BudgetProgressWidget',
    'WalletBalanceWidget',
    'ExpenseChartWidget'
]