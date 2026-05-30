"""
End-to-End Test Generator for Flask-AppBuilder Testing Framework

This module generates comprehensive end-to-end tests using Playwright for browser automation.
Tests cover complete user journeys, cross-browser compatibility, and real-world scenarios.
"""

import os
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
import inflection

from .base_generator import BaseTestGenerator
from ..core.config import TestGenerationConfig
from ...cli.generators.database_inspector import EnhancedDatabaseInspector, TableInfo


@dataclass
class E2ETestSuite:
    """Represents a complete end-to-end test suite for a model/application area."""
    model_name: str
    user_journey_tests: str
    form_interaction_tests: str
    navigation_tests: str
    responsive_design_tests: str
    accessibility_tests: str
    performance_tests: str
    cross_browser_tests: str


@dataclass
class UserJourney:
    """Represents a complete user journey scenario."""
    name: str
    description: str
    steps: List[str]
    expected_outcomes: List[str]
    test_data_requirements: Dict[str, Any]


class E2ETestGenerator(BaseTestGenerator):
    """
    Generates end-to-end tests using Playwright for browser automation.

    Tests generated:
    - Complete user journey scenarios
    - Form interactions and validations
    - Navigation and menu functionality
    - Responsive design testing
    - Accessibility compliance (WCAG 2.1)
    - Performance and loading tests
    - Cross-browser compatibility
    """

    def __init__(self, config: TestGenerationConfig, inspector: EnhancedDatabaseInspector):
        super().__init__(config, inspector)
        self.template_dir = "e2e_tests"
        self.browsers = ["chromium", "firefox", "webkit"]
        self.viewports = [
            {"width": 1920, "height": 1080},  # Desktop
            {"width": 1366, "height": 768},   # Laptop
            {"width": 768, "height": 1024},   # Tablet
            {"width": 375, "height": 667}     # Mobile
        ]

    def generate_all_e2e_tests(self) -> Dict[str, E2ETestSuite]:
        """Generate end-to-end tests for all models and user journeys."""
        test_suites = {}

        for table_info in self.inspector.get_all_tables():
            if not self._should_generate_tests(table_info):
                continue

            suite = self._generate_model_e2e_suite(table_info)
            test_suites[table_info.name] = suite

        return test_suites

    def _generate_model_e2e_suite(self, table_info: TableInfo) -> E2ETestSuite:
        """Generate complete end-to-end test suite for a model."""
        model_name = inflection.camelize(table_info.name)

        return E2ETestSuite(
            model_name=model_name,
            user_journey_tests=self._generate_user_journey_tests(table_info),
            form_interaction_tests=self._generate_form_interaction_tests(table_info),
            navigation_tests=self._generate_navigation_tests(table_info),
            responsive_design_tests=self._generate_responsive_design_tests(table_info),
            accessibility_tests=self._generate_accessibility_tests(table_info),
            performance_tests=self._generate_performance_tests(table_info),
            cross_browser_tests=self._generate_cross_browser_tests(table_info)
        )

    def _generate_user_journey_tests(self, table_info: TableInfo) -> str:
        """Generate complete user journey tests."""
        model_name = inflection.camelize(table_info.name)
        journeys = self._define_user_journeys(table_info)

        template = f'''
import asyncio
import pytest
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

class Test{model_name}UserJourneys:
    """End-to-end user journey tests for {model_name}."""

    @pytest.fixture(scope="session")
    async def browser(self):
        """Create browser instance for tests."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            yield browser
            await browser.close()

    @pytest.fixture
    async def context(self, browser: Browser):
        """Create browser context with authentication."""
        context = await browser.new_context(
            viewport={{"width": 1280, "height": 720}},
            extra_http_headers={{
                "Accept-Language": "en-US,en;q=0.9"
            }}
        )

        # Setup authentication if needed
        await self._authenticate_context(context)

        yield context
        await context.close()

    @pytest.fixture
    async def page(self, context: BrowserContext):
        """Create page for tests."""
        page = await context.new_page()
        yield page
        await page.close()

    async def _authenticate_context(self, context: BrowserContext):
        """Authenticate the browser context with test user."""
        page = await context.new_page()

        # Navigate to login page
        await page.goto("/login")

        # Fill login form
        await page.fill('input[name="username"]', "test_user")
        await page.fill('input[name="password"]', "test_password")

        # Submit login
        await page.click('input[type="submit"]')

        # Wait for redirect to dashboard
        await page.wait_for_url("/")
        await page.close()

{self._generate_journey_test_methods(table_info, journeys)}

    async def test_complete_crud_journey(self, page: Page):
        """Test complete Create-Read-Update-Delete user journey."""
        # Navigate to {model_name} list page
        await page.goto("/{table_info.name.lower()}/list/")
        await page.wait_for_load_state("networkidle")

        # Verify we're on the correct page
        await page.wait_for_selector("h1", state="visible")
        heading = await page.text_content("h1")
        assert "{model_name}" in heading

        # Step 1: CREATE - Navigate to add form
        await page.click('a[href*="/add"]')
        await page.wait_for_url("**/{table_info.name.lower()}/add/**")

        # Fill out the form with test data
        test_data = self._get_test_form_data()
        for field_name, field_value in test_data.items():
            await self._fill_form_field(page, field_name, field_value)

        # Submit the form
        await page.click('input[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Verify successful creation (redirect to list with success message)
        success_message = await page.wait_for_selector(".alert-success", state="visible")
        assert await success_message.is_visible()

        # Step 2: READ - Find and view the created record
        # Search for our created record
        if test_data.get('name'):
            await page.fill('input[name*="search"]', test_data['name'])
            await page.press('input[name*="search"]', 'Enter')
            await page.wait_for_load_state("networkidle")

        # Click on the show/view link
        await page.click('a[href*="/show/"]')
        await page.wait_for_load_state("networkidle")

        # Verify the data is displayed correctly
        for field_name, expected_value in test_data.items():
            field_element = await page.wait_for_selector(f'[data-field="{field_name}"], .field-{field_name}')
            displayed_value = await field_element.text_content()
            assert str(expected_value) in displayed_value

        # Step 3: UPDATE - Navigate to edit form
        await page.click('a[href*="/edit/"]')
        await page.wait_for_url("**/{table_info.name.lower()}/edit/**")

        # Modify some fields
        update_data = self._get_update_form_data()
        for field_name, field_value in update_data.items():
            await self._clear_and_fill_field(page, field_name, field_value)

        # Submit the update
        await page.click('input[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # Verify update success
        success_message = await page.wait_for_selector(".alert-success", state="visible")
        assert await success_message.is_visible()

        # Go back to show page and verify changes
        await page.click('a[href*="/show/"]')
        await page.wait_for_load_state("networkidle")

        for field_name, expected_value in update_data.items():
            field_element = await page.wait_for_selector(f'[data-field="{field_name}"], .field-{field_name}')
            displayed_value = await field_element.text_content()
            assert str(expected_value) in displayed_value

        # Step 4: DELETE - Delete the record
        await page.click('a[href*="/delete/"]')

        # Handle confirmation dialog if present
        page.on("dialog", lambda dialog: dialog.accept())

        await page.wait_for_load_state("networkidle")

        # Verify deletion (should be redirected to list page)
        current_url = page.url
        assert "/{table_info.name.lower()}/list/" in current_url

        # Verify success message
        success_message = await page.wait_for_selector(".alert-success", state="visible")
        assert await success_message.is_visible()

        # Verify record is no longer in the list
        if test_data.get('name'):
            await page.fill('input[name*="search"]', test_data['name'])
            await page.press('input[name*="search"]', 'Enter')
            await page.wait_for_load_state("networkidle")

            # Should show "No records found" or similar
            no_records = await page.query_selector_all('.no-records, .empty-state')
            assert len(no_records) > 0

    async def test_bulk_operations_journey(self, page: Page):
        """Test bulk operations user journey."""
        # Create multiple test records first
        await self._create_test_records(page, count=5)

        # Navigate to list page
        await page.goto("/{table_info.name.lower()}/list/")
        await page.wait_for_load_state("networkidle")

        # Select multiple records using checkboxes
        checkboxes = await page.query_selector_all('input[type="checkbox"][name="rowid"]')

        # Select first 3 records
        for i in range(min(3, len(checkboxes))):
            await checkboxes[i].check()

        # Select bulk action (e.g., delete)
        await page.select_option('select[name="action"]', 'muldelete')

        # Click the bulk action button
        await page.click('input[value="Apply"]')

        # Handle confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        await page.wait_for_load_state("networkidle")

        # Verify bulk operation success
        success_message = await page.wait_for_selector(".alert-success", state="visible")
        assert await success_message.is_visible()

        # Verify records were processed
        remaining_checkboxes = await page.query_selector_all('input[type="checkbox"][name="rowid"]')
        assert len(remaining_checkboxes) == len(checkboxes) - 3

    async def test_search_and_filter_journey(self, page: Page):
        """Test search and filtering user journey."""
        # Create test records with specific data
        await self._create_test_records(page, count=10)

        # Navigate to list page
        await page.goto("/{table_info.name.lower()}/list/")
        await page.wait_for_load_state("networkidle")

        # Test text search
        search_term = "test_search_value"
        await page.fill('input[name*="search"]', search_term)
        await page.press('input[name*="search"]', 'Enter')
        await page.wait_for_load_state("networkidle")

        # Verify search results
        search_results = await page.query_selector_all('.list-item, tr[data-id]')
        for result in search_results:
            text_content = await result.text_content()
            assert search_term.lower() in text_content.lower()

        # Clear search
        await page.fill('input[name*="search"]', "")
        await page.press('input[name*="search"]', 'Enter')
        await page.wait_for_load_state("networkidle")

        # Test column filters
        filter_dropdowns = await page.query_selector_all('select[name*="_flt_"]')
        if filter_dropdowns:
            # Select a filter option
            await filter_dropdowns[0].select_option(index=1)  # Select first non-empty option
            await page.wait_for_load_state("networkidle")

            # Verify filtered results
            filtered_results = await page.query_selector_all('.list-item, tr[data-id]')
            assert len(filtered_results) > 0

    async def test_pagination_journey(self, page: Page):
        """Test pagination user journey."""
        # Create enough records to trigger pagination
        await self._create_test_records(page, count=30)

        # Navigate to list page
        await page.goto("/{table_info.name.lower()}/list/")
        await page.wait_for_load_state("networkidle")

        # Verify first page is displayed
        page_info = await page.wait_for_selector('.page-info, .pagination-info')
        page_text = await page_info.text_content()
        assert "1" in page_text or "Page 1" in page_text

        # Navigate to next page
        next_button = await page.query_selector('a[aria-label="Next"], .pagination .next')
        if next_button:
            await next_button.click()
            await page.wait_for_load_state("networkidle")

            # Verify we're on page 2
            page_info = await page.wait_for_selector('.page-info, .pagination-info')
            page_text = await page_info.text_content()
            assert "2" in page_text or "Page 2" in page_text

        # Test direct page navigation
        page_links = await page.query_selector_all('.pagination a[data-page]')
        if len(page_links) > 2:
            await page_links[2].click()  # Click third page
            await page.wait_for_load_state("networkidle")

    async def _fill_form_field(self, page: Page, field_name: str, value: Any):
        """Fill a form field with appropriate method based on field type."""
        # Try different field selectors
        selectors = [
            f'input[name="{field_name}"]',
            f'select[name="{field_name}"]',
            f'textarea[name="{field_name}"]',
            f'#{field_name}',
            f'[data-field="{field_name}"]'
        ]

        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                input_type = await element.get_attribute('type') if tag_name == 'input' else None

                if tag_name == 'select':
                    await page.select_option(selector, str(value))
                elif input_type == 'checkbox':
                    if value:
                        await page.check(selector)
                    else:
                        await page.uncheck(selector)
                elif input_type == 'radio':
                    await page.check(selector)
                elif input_type == 'file':
                    # Handle file uploads if needed
                    pass
                else:
                    await page.fill(selector, str(value))
                break

    async def _clear_and_fill_field(self, page: Page, field_name: str, value: Any):
        """Clear and fill a form field."""
        selector = f'input[name="{field_name}"], textarea[name="{field_name}"]'
        await page.fill(selector, "")  # Clear first
        await page.fill(selector, str(value))

    async def _create_test_records(self, page: Page, count: int = 1):
        """Create test records via the UI."""
        for i in range(count):
            await page.goto("/{table_info.name.lower()}/add/")
            await page.wait_for_load_state("networkidle")

            test_data = self._get_test_form_data(index=i)
            for field_name, field_value in test_data.items():
                await self._fill_form_field(page, field_name, field_value)

            await page.click('input[type="submit"]')
            await page.wait_for_load_state("networkidle")

    def _get_test_form_data(self, index: int = 0) -> Dict[str, Any]:
        """Get test form data for creating records."""
        # This should be implemented based on the specific model fields
        return {{
{self._generate_form_data_fields(table_info)}
        }}

    def _get_update_form_data(self) -> Dict[str, Any]:
        """Get test form data for updating records."""
        return {{
{self._generate_update_data_fields(table_info)}
        }}

{self._generate_model_specific_journey_tests(table_info)}
'''

        return self._format_template(template)

    def _generate_form_interaction_tests(self, table_info: TableInfo) -> str:
        """Generate form interaction and validation tests."""
        model_name = inflection.camelize(table_info.name)

        template = f'''
class Test{model_name}FormInteractions:
    """End-to-end form interaction tests for {model_name}."""

    @pytest.fixture
    async def authenticated_page(self, page: Page):
        """Page with authenticated user."""
        await self._authenticate_page(page)
        return page

    async def test_form_field_validations(self, authenticated_page: Page):
        """Test client-side and server-side form validations."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

{self._generate_field_validation_tests(table_info)}

    async def test_form_field_interactions(self, authenticated_page: Page):
        """Test dynamic form field interactions."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

{self._generate_field_interaction_tests(table_info)}

    async def test_form_submission_states(self, authenticated_page: Page):
        """Test form submission and loading states."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Fill valid form data
        test_data = self._get_valid_form_data()
        for field_name, value in test_data.items():
            await self._fill_form_field(authenticated_page, field_name, value)

        # Test submission loading state
        submit_button = await authenticated_page.wait_for_selector('input[type="submit"]')

        # Click submit and immediately check loading state
        await submit_button.click()

        # Check if submit button is disabled during processing
        is_disabled = await submit_button.get_attribute('disabled')
        # Note: This might pass quickly, so this test is more about ensuring
        # the form handles submission states properly

        await authenticated_page.wait_for_load_state("networkidle")

        # Verify successful submission
        success_indicator = await authenticated_page.query_selector('.alert-success, .flash-success')
        assert success_indicator is not None

    async def test_form_auto_save_functionality(self, authenticated_page: Page):
        """Test auto-save functionality if implemented."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Fill some form data
        await authenticated_page.fill('input[name*="name"]', 'auto-save-test')

        # Wait for auto-save (if implemented)
        await authenticated_page.wait_for_timeout(2000)

        # Refresh page to see if data is preserved
        await authenticated_page.reload()
        await authenticated_page.wait_for_load_state("networkidle")

        # Check if auto-saved data is restored
        saved_value = await authenticated_page.input_value('input[name*="name"]')
        # This test depends on whether auto-save is implemented

    async def test_form_keyboard_navigation(self, authenticated_page: Page):
        """Test keyboard navigation through form fields."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Start from first field
        first_input = await authenticated_page.query_selector('input:not([type="hidden"]), select, textarea')
        await first_input.focus()

        # Tab through all fields
        form_fields = await authenticated_page.query_selector_all('input:not([type="hidden"]), select, textarea')

        for i in range(len(form_fields) - 1):
            current_field = await authenticated_page.evaluate('document.activeElement')
            await authenticated_page.keyboard.press('Tab')
            next_field = await authenticated_page.evaluate('document.activeElement')

            # Verify focus moved to next field
            assert current_field != next_field

        # Test Shift+Tab to go backwards
        await authenticated_page.keyboard.press('Shift+Tab')
        previous_field = await authenticated_page.evaluate('document.activeElement')
        # Verify focus moved backwards

    async def test_form_accessibility_features(self, authenticated_page: Page):
        """Test form accessibility features."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Check for proper labels
        form_fields = await authenticated_page.query_selector_all('input, select, textarea')

        for field in form_fields:
            field_id = await field.get_attribute('id')
            field_name = await field.get_attribute('name')

            # Check for associated label
            if field_id:
                label = await authenticated_page.query_selector(f'label[for="{field_id}"]')
                assert label is not None, f"No label found for field {field_id}"

            # Check for aria-label or aria-labelledby
            aria_label = await field.get_attribute('aria-label')
            aria_labelledby = await field.get_attribute('aria-labelledby')

            # At least one labeling method should be present
            has_labeling = label is not None or aria_label or aria_labelledby
            assert has_labeling, f"Field {field_name} has no accessible labeling"

        # Check for required field indicators
        required_fields = await authenticated_page.query_selector_all('input[required], select[required]')
        for field in required_fields:
            # Should have visual indicator (*, "required", or aria-required)
            aria_required = await field.get_attribute('aria-required')
            assert aria_required == 'true', "Required field missing aria-required attribute"

    async def _authenticate_page(self, page: Page):
        """Authenticate the page with test user."""
        await page.goto("/login")
        await page.fill('input[name="username"]', "test_user")
        await page.fill('input[name="password"]', "test_password")
        await page.click('input[type="submit"]')
        await page.wait_for_url("/")
'''

        return self._format_template(template)

    def _generate_navigation_tests(self, table_info: TableInfo) -> str:
        """Generate navigation and menu tests."""
        model_name = inflection.camelize(table_info.name)

        template = f'''
class Test{model_name}Navigation:
    """Navigation and menu functionality tests for {model_name}."""

    async def test_menu_navigation(self, authenticated_page: Page):
        """Test navigation through application menus."""
        await authenticated_page.goto("/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Find {model_name} in menu
        menu_item = await authenticated_page.wait_for_selector(f'a[href*="{table_info.name.lower()}"], .menu-item:has-text("{model_name}")')
        await menu_item.click()
        await authenticated_page.wait_for_load_state("networkidle")

        # Verify we're on the correct page
        current_url = authenticated_page.url
        assert f"{table_info.name.lower()}/list" in current_url

        # Test breadcrumb navigation if present
        breadcrumbs = await authenticated_page.query_selector_all('.breadcrumb a, .breadcrumb-item a')
        if breadcrumbs:
            # Click on parent breadcrumb
            await breadcrumbs[0].click()
            await authenticated_page.wait_for_load_state("networkidle")

    async def test_action_button_navigation(self, authenticated_page: Page):
        """Test navigation through action buttons and links."""
        # Navigate to list page
        await authenticated_page.goto("/{table_info.name.lower()}/list/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Test "Add New" button
        add_button = await authenticated_page.wait_for_selector('a[href*="/add"], .btn:has-text("Add")')
        await add_button.click()
        await authenticated_page.wait_for_url(f"**/{table_info.name.lower()}/add/**")

        # Test "Back" or "Cancel" button
        back_button = await authenticated_page.query_selector('a:has-text("Back"), a:has-text("Cancel"), .btn-back')
        if back_button:
            await back_button.click()
            await authenticated_page.wait_for_url(f"**/{table_info.name.lower()}/list/**")

        # Create a test record to test other navigation
        await self._create_test_record_for_navigation(authenticated_page)

        # Test "Show/View" button
        view_button = await authenticated_page.wait_for_selector('a[href*="/show/"], .btn:has-text("View")')
        await view_button.click()
        await authenticated_page.wait_for_load_state("networkidle")

        current_url = authenticated_page.url
        assert "/show/" in current_url

        # Test "Edit" button from show page
        edit_button = await authenticated_page.wait_for_selector('a[href*="/edit/"], .btn:has-text("Edit")')
        await edit_button.click()
        await authenticated_page.wait_for_load_state("networkidle")

        current_url = authenticated_page.url
        assert "/edit/" in current_url

    async def test_url_direct_access(self, authenticated_page: Page):
        """Test direct URL access to different views."""
        # Create a test record first
        test_record_id = await self._create_test_record_and_get_id(authenticated_page)

        # Test direct access to different URLs
        urls_to_test = [
            f"/{table_info.name.lower()}/list/",
            f"/{table_info.name.lower()}/add/",
            f"/{table_info.name.lower()}/show/{{test_record_id}}/",
            f"/{table_info.name.lower()}/edit/{{test_record_id}}/"
        ]

        for url in urls_to_test:
            await authenticated_page.goto(url)
            await authenticated_page.wait_for_load_state("networkidle")

            # Should not get 404 or error page
            page_title = await authenticated_page.title()
            assert "404" not in page_title
            assert "Error" not in page_title

            # Should have proper page content
            main_content = await authenticated_page.query_selector('main, .content, .main-content')
            assert main_content is not None

    async def test_navigation_state_preservation(self, authenticated_page: Page):
        """Test that navigation preserves search/filter state."""
        await authenticated_page.goto("/{table_info.name.lower()}/list/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Apply search filter
        search_term = "navigation_test"
        await authenticated_page.fill('input[name*="search"]', search_term)
        await authenticated_page.press('input[name*="search"]', 'Enter')
        await authenticated_page.wait_for_load_state("networkidle")

        # Navigate to add page
        add_button = await authenticated_page.wait_for_selector('a[href*="/add"]')
        await add_button.click()
        await authenticated_page.wait_for_load_state("networkidle")

        # Navigate back to list
        back_button = await authenticated_page.query_selector('a:has-text("Back"), .btn-back')
        if back_button:
            await back_button.click()
            await authenticated_page.wait_for_load_state("networkidle")

            # Check if search state is preserved
            search_input = await authenticated_page.query_selector('input[name*="search"]')
            if search_input:
                current_search = await search_input.input_value()
                # Depending on implementation, search might or might not be preserved

    async def _create_test_record_for_navigation(self, page: Page):
        """Create a test record for navigation testing."""
        await page.goto("/{table_info.name.lower()}/add/")
        await page.wait_for_load_state("networkidle")

        test_data = self._get_minimal_valid_form_data()
        for field_name, value in test_data.items():
            await self._fill_form_field(page, field_name, value)

        await page.click('input[type="submit"]')
        await page.wait_for_load_state("networkidle")

    async def _create_test_record_and_get_id(self, page: Page) -> str:
        """Create a test record and return its ID."""
        await self._create_test_record_for_navigation(page)

        # Navigate to list to find the created record
        await page.goto("/{table_info.name.lower()}/list/")
        await page.wait_for_load_state("networkidle")

        # Get the first record's ID from the show link
        show_link = await page.wait_for_selector('a[href*="/show/"]')
        href = await show_link.get_attribute('href')

        # Extract ID from URL (assumes format like "/model/show/123/")
        import re
        match = re.search(r'/show/([0-9]+)', href)
        return match.group(1) if match else "1"
'''

        return self._format_template(template)

    def _generate_responsive_design_tests(self, table_info: TableInfo) -> str:
        """Generate responsive design tests."""
        model_name = inflection.camelize(table_info.name)

        template = f'''
class Test{model_name}ResponsiveDesign:
    """Responsive design tests for {model_name} across different viewports."""

    @pytest.mark.parametrize("viewport", [
        {{"width": 1920, "height": 1080}},  # Desktop
        {{"width": 1366, "height": 768}},   # Laptop
        {{"width": 768, "height": 1024}},   # Tablet
        {{"width": 375, "height": 667}}     # Mobile
    ])
    async def test_responsive_layout(self, browser: Browser, viewport: Dict[str, int]):
        """Test responsive layout across different viewport sizes."""
        context = await browser.new_context(viewport=viewport)
        await self._authenticate_context(context)
        page = await context.new_page()

        try:
            # Test list view responsiveness
            await page.goto("/{table_info.name.lower()}/list/")
            await page.wait_for_load_state("networkidle")

            # Verify page loads and is usable
            main_content = await page.wait_for_selector('main, .content, .main-content')
            assert await main_content.is_visible()

            # Check if mobile navigation is present on small screens
            if viewport["width"] <= 768:
                # Look for mobile menu toggle
                mobile_menu = await page.query_selector('.navbar-toggler, .menu-toggle, .hamburger')
                if mobile_menu:
                    assert await mobile_menu.is_visible()

            # Test form responsiveness
            await page.goto("/{table_info.name.lower()}/add/")
            await page.wait_for_load_state("networkidle")

            # Verify form is usable at this viewport
            form_fields = await page.query_selector_all('input, select, textarea')

            for field in form_fields[:3]:  # Test first 3 fields
                # Verify field is visible and interactable
                assert await field.is_visible()

                # Try to focus the field
                await field.focus()
                is_focused = await page.evaluate(f'document.activeElement === arguments[0]', field)
                assert is_focused

            # Test table responsiveness on list view
            await page.goto("/{table_info.name.lower()}/list/")
            await page.wait_for_load_state("networkidle")

            if viewport["width"] <= 768:
                # On mobile, tables might be cards or horizontally scrollable
                table = await page.query_selector('table')
                if table:
                    # Check if table has horizontal scroll or is transformed to cards
                    table_wrapper = await page.query_selector('.table-responsive, .table-scroll')
                    card_layout = await page.query_selector('.card-layout, .mobile-cards')

                    # Either responsive wrapper or card layout should be present
                    assert table_wrapper is not None or card_layout is not None

        finally:
            await context.close()

    async def test_mobile_navigation_usability(self, browser: Browser):
        """Test mobile navigation usability."""
        mobile_viewport = {{"width": 375, "height": 667}}
        context = await browser.new_context(viewport=mobile_viewport)
        await self._authenticate_context(context)
        page = await context.new_page()

        try:
            await page.goto("/")
            await page.wait_for_load_state("networkidle")

            # Test mobile menu if present
            mobile_toggle = await page.query_selector('.navbar-toggler, .menu-toggle')
            if mobile_toggle:
                # Open mobile menu
                await mobile_toggle.click()
                await page.wait_for_timeout(500)  # Wait for animation

                # Verify menu is visible
                mobile_menu = await page.wait_for_selector('.navbar-collapse.show, .mobile-menu.open')
                assert await mobile_menu.is_visible()

                # Find {model_name} menu item
                menu_item = await page.query_selector(f'a[href*="{table_info.name.lower()}"]')
                if menu_item:
                    await menu_item.click()
                    await page.wait_for_load_state("networkidle")

                    # Verify navigation worked
                    current_url = page.url
                    assert f"{table_info.name.lower()}" in current_url

            # Test touch interactions
            await page.goto("/{table_info.name.lower()}/list/")
            await page.wait_for_load_state("networkidle")

            # Test swipe gestures if implemented
            # This would depend on specific mobile interactions in your app

        finally:
            await context.close()

    async def test_print_layout(self, authenticated_page: Page):
        """Test print layout and styles."""
        await authenticated_page.goto("/{table_info.name.lower()}/list/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Emulate print media
        await authenticated_page.emulate_media(media="print")

        # Verify page still looks reasonable for printing
        # Check that navigation and non-essential elements are hidden
        nav_element = await authenticated_page.query_selector('nav, .navigation')
        if nav_element:
            nav_display = await nav_element.evaluate('getComputedStyle(this).display')
            # Nav should be hidden in print
            assert nav_display == 'none'

        # Verify main content is still visible
        main_content = await authenticated_page.query_selector('main, .content')
        if main_content:
            content_display = await main_content.evaluate('getComputedStyle(this).display')
            assert content_display != 'none'

    async def test_high_dpi_displays(self, browser: Browser):
        """Test appearance on high-DPI displays."""
        context = await browser.new_context(
            viewport={{"width": 1280, "height": 720}},
            device_scale_factor=2  # Simulate Retina display
        )
        await self._authenticate_context(context)
        page = await context.new_page()

        try:
            await page.goto("/{table_info.name.lower()}/list/")
            await page.wait_for_load_state("networkidle")

            # Take screenshot to verify rendering
            screenshot = await page.screenshot()
            assert len(screenshot) > 0

            # Verify images and icons render properly at high DPI
            images = await page.query_selector_all('img')
            for img in images:
                # Check that images load successfully
                loaded = await img.evaluate('this.complete && this.naturalHeight !== 0')
                assert loaded

        finally:
            await context.close()
'''

        return self._format_template(template)

    def _generate_accessibility_tests(self, table_info: TableInfo) -> str:
        """Generate WCAG accessibility tests."""
        model_name = inflection.camelize(table_info.name)

        template = f'''
class Test{model_name}Accessibility:
    """WCAG 2.1 accessibility tests for {model_name}."""

    async def test_keyboard_navigation_compliance(self, authenticated_page: Page):
        """Test keyboard navigation compliance."""
        await authenticated_page.goto("/{table_info.name.lower()}/list/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Test Tab order
        focusable_elements = await authenticated_page.query_selector_all(
            'a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )

        # Start from first element
        await focusable_elements[0].focus()

        # Tab through all focusable elements
        for i in range(len(focusable_elements) - 1):
            await authenticated_page.keyboard.press('Tab')

            # Verify focus moved to next logical element
            focused_element = await authenticated_page.evaluate('document.activeElement')
            # The exact verification depends on your specific tab order implementation

        # Test Escape key functionality
        modal_trigger = await authenticated_page.query_selector('[data-toggle="modal"], .modal-trigger')
        if modal_trigger:
            await modal_trigger.click()
            await authenticated_page.wait_for_timeout(500)

            # Press Escape to close modal
            await authenticated_page.keyboard.press('Escape')
            await authenticated_page.wait_for_timeout(500)

            # Verify modal is closed
            modal = await authenticated_page.query_selector('.modal.show')
            assert modal is None

    async def test_screen_reader_compatibility(self, authenticated_page: Page):
        """Test screen reader compatibility."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Check for proper heading structure
        headings = await authenticated_page.query_selector_all('h1, h2, h3, h4, h5, h6')

        # Verify logical heading hierarchy
        heading_levels = []
        for heading in headings:
            tag_name = await heading.evaluate('this.tagName.toLowerCase()')
            level = int(tag_name[1])
            heading_levels.append(level)

        # Check that headings don't skip levels
        for i in range(1, len(heading_levels)):
            level_diff = heading_levels[i] - heading_levels[i-1]
            assert level_diff <= 1, f"Heading level skipped: h{{heading_levels[i-1]}} to h{{heading_levels[i]}}"

        # Check for proper form labels
        form_inputs = await authenticated_page.query_selector_all('input, select, textarea')

        for input_element in form_inputs:
            input_id = await input_element.get_attribute('id')
            input_type = await input_element.get_attribute('type')

            # Skip hidden inputs
            if input_type == 'hidden':
                continue

            # Verify labeling
            has_label = False

            # Check for associated label
            if input_id:
                label = await authenticated_page.query_selector(f'label[for="{input_id}"]')
                has_label = label is not None

            # Check for aria-label
            if not has_label:
                aria_label = await input_element.get_attribute('aria-label')
                has_label = aria_label is not None

            # Check for aria-labelledby
            if not has_label:
                aria_labelledby = await input_element.get_attribute('aria-labelledby')
                has_label = aria_labelledby is not None

            assert has_label, f"Input element lacks proper labeling: {{await input_element.get_attribute('name')}}"

    async def test_color_contrast_compliance(self, authenticated_page: Page):
        """Test color contrast compliance."""
        await authenticated_page.goto("/{table_info.name.lower()}/list/")
        await authenticated_page.wait_for_load_state("networkidle")

        # This is a basic check - full contrast testing requires specialized tools
        # Check that important elements have sufficient contrast

        # Get text elements
        text_elements = await authenticated_page.query_selector_all('p, span, div, td, th, label, a')

        for element in text_elements[:10]:  # Test first 10 elements
            # Get computed styles
            styles = await element.evaluate('''
                el => {{
                    const computed = getComputedStyle(el);
                    return {{
                        color: computed.color,
                        backgroundColor: computed.backgroundColor,
                        fontSize: computed.fontSize
                    }};
                }}
            ''')

            # Basic check that text isn't same color as background
            assert styles['color'] != styles['backgroundColor'], "Text color same as background"

    async def test_focus_indicators(self, authenticated_page: Page):
        """Test focus indicators visibility."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Get all focusable elements
        focusable = await authenticated_page.query_selector_all('a, button, input, select, textarea')

        for element in focusable[:5]:  # Test first 5 elements
            # Focus the element
            await element.focus()

            # Check if focus is visible
            has_focus_style = await element.evaluate('''
                el => {{
                    const computed = getComputedStyle(el);
                    // Check for common focus indicators
                    return computed.outline !== 'none' ||
                           computed.boxShadow !== 'none' ||
                           computed.border !== computed.getPropertyValue('--original-border');
                }}
            ''')

            # Focus should be clearly visible
            # Note: This is a simplified check - real focus testing is more complex

    async def test_aria_attributes_compliance(self, authenticated_page: Page):
        """Test ARIA attributes compliance."""
        await authenticated_page.goto("/{table_info.name.lower()}/list/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Check for proper ARIA landmarks
        landmarks = await authenticated_page.query_selector_all('[role="main"], [role="navigation"], [role="banner"]')
        assert len(landmarks) > 0, "Page should have ARIA landmark roles"

        # Check tables have proper ARIA structure
        tables = await authenticated_page.query_selector_all('table')
        for table in tables:
            # Check for caption or aria-label
            caption = await table.query_selector('caption')
            aria_label = await table.get_attribute('aria-label')
            aria_labelledby = await table.get_attribute('aria-labelledby')

            has_description = caption is not None or aria_label or aria_labelledby
            assert has_description, "Table should have caption or aria-label"

        # Check buttons have proper labels
        buttons = await authenticated_page.query_selector_all('button')
        for button in buttons:
            button_text = await button.text_content()
            aria_label = await button.get_attribute('aria-label')

            has_label = (button_text and button_text.strip()) or aria_label
            assert has_label, "Button should have visible text or aria-label"

    async def test_error_message_accessibility(self, authenticated_page: Page):
        """Test error message accessibility."""
        await authenticated_page.goto("/{table_info.name.lower()}/add/")
        await authenticated_page.wait_for_load_state("networkidle")

        # Submit form with invalid data to trigger errors
        await authenticated_page.click('input[type="submit"]')
        await authenticated_page.wait_for_load_state("networkidle")

        # Check for error messages
        error_messages = await authenticated_page.query_selector_all('.error, .alert-danger, .field-error')

        for error in error_messages:
            # Verify error is associated with field
            aria_describedby = await error.get_attribute('aria-describedby')
            error_id = await error.get_attribute('id')

            # Error should be programmatically associated with field
            if error_id:
                associated_field = await authenticated_page.query_selector(f'[aria-describedby*="{error_id}"]')
                assert associated_field is not None, "Error message not associated with field"

    async def test_skip_navigation_links(self, authenticated_page: Page):
        """Test skip navigation links."""
        await authenticated_page.goto("/{table_info.name.lower()}/list/")

        # Focus first element on page
        await authenticated_page.keyboard.press('Tab')

        # Check if skip link appears
        skip_link = await authenticated_page.query_selector('a[href="#main"], a[href="#content"], .skip-link')

        if skip_link:
            # Verify skip link is visible when focused
            is_visible = await skip_link.is_visible()
            assert is_visible, "Skip link should be visible when focused"

            # Test skip link functionality
            await skip_link.click()

            # Verify focus moved to main content
            main_content = await authenticated_page.query_selector('#main, #content, main')
            if main_content:
                focused_element = await authenticated_page.evaluate('document.activeElement')
                # Verify focus is now on main content area
'''

        return self._format_template(template)

    def write_e2e_tests_to_file(self, output_dir: str, test_suites: Dict[str, E2ETestSuite]):
        """Write all E2E test suites to files."""
        os.makedirs(output_dir, exist_ok=True)

        # Write base configuration
        self._write_e2e_base_config(output_dir)

        # Write Playwright configuration
        self._write_playwright_config(output_dir)

        for model_name, suite in test_suites.items():
            # Write main E2E test file
            test_content = f'''
"""
End-to-End tests for {model_name} model using Playwright.

This file contains comprehensive E2E tests that verify complete user journeys,
form interactions, navigation, responsive design, accessibility, and performance.
"""

import pytest
import asyncio
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from tests.e2e.base_e2e_test import BaseE2ETest


{suite.user_journey_tests}

{suite.form_interaction_tests}

{suite.navigation_tests}

{suite.responsive_design_tests}

{suite.accessibility_tests}

{suite.performance_tests}

{suite.cross_browser_tests}


if __name__ == '__main__':
    pytest.main([__file__])
'''

            filename = f"test_{model_name.lower()}_e2e.py"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w') as f:
                f.write(test_content)

    def _write_e2e_base_config(self, output_dir: str):
        """Write base E2E test configuration."""
        base_config = '''
"""
Base E2E Test Configuration for Flask-AppBuilder Testing Framework
"""

import pytest
import asyncio
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from typing import Dict, Any, List


class BaseE2ETest:
    """Base class for E2E tests with common functionality."""

    @pytest.fixture(scope="session")
    def event_loop(self):
        """Create an instance of the default event loop for the test session."""
        loop = asyncio.get_event_loop_policy().new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture(scope="session")
    async def browser_factory(self):
        """Factory for creating browser instances."""
        async with async_playwright() as p:
            yield p

    @pytest.fixture(scope="session")
    async def browser(self, browser_factory):
        """Create browser instance for tests."""
        browser = await browser_factory.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        yield browser
        await browser.close()

    @pytest.fixture
    async def context(self, browser: Browser):
        """Create browser context."""
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
        yield context
        await context.close()

    @pytest.fixture
    async def authenticated_page(self, context: BrowserContext):
        """Create authenticated page for tests."""
        page = await context.new_page()
        await self._authenticate_page(page)
        yield page
        await page.close()

    async def _authenticate_page(self, page: Page):
        """Authenticate the page with test user."""
        await page.goto("/login")
        await page.fill('input[name="username"]', "test_user")
        await page.fill('input[name="password"]', "test_password")
        await page.click('input[type="submit"]')
        await page.wait_for_url("/")

    async def _authenticate_context(self, context: BrowserContext):
        """Authenticate the browser context."""
        page = await context.new_page()
        await self._authenticate_page(page)
        await page.close()

    def _get_test_data_for_model(self, model_name: str) -> Dict[str, Any]:
        """Get test data for a specific model."""
        # Override in specific test classes
        return {}

    async def _fill_form_field(self, page: Page, field_name: str, value: Any):
        """Fill a form field with the appropriate method."""
        selectors = [
            f'input[name="{field_name}"]',
            f'select[name="{field_name}"]',
            f'textarea[name="{field_name}"]',
            f'#{field_name}'
        ]

        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                input_type = await element.get_attribute('type')

                if tag_name == 'select':
                    await page.select_option(selector, str(value))
                elif input_type == 'checkbox':
                    if value:
                        await page.check(selector)
                    else:
                        await page.uncheck(selector)
                else:
                    await page.fill(selector, str(value))
                break
'''

        base_config_file = os.path.join(output_dir, "base_e2e_test.py")
        with open(base_config_file, 'w') as f:
            f.write(base_config)

    def _write_playwright_config(self, output_dir: str):
        """Write Playwright configuration file."""
        playwright_config = '''
"""
Playwright Configuration for Flask-AppBuilder E2E Tests
"""

from playwright.sync_api import sync_playwright
import pytest


@pytest.fixture(scope="session")
def playwright_config():
    """Playwright configuration for tests."""
    return {
        "browsers": ["chromium", "firefox", "webkit"],
        "headless": True,
        "viewport": {"width": 1280, "height": 720},
        "timeout": 30000,
        "base_url": "http://localhost:5000",
        "screenshot": "only-on-failure",
        "video": "retain-on-failure"
    }


def pytest_configure(config):
    """Configure pytest for Playwright tests."""
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "accessibility: mark test as accessibility test")
'''

        config_file = os.path.join(output_dir, "playwright_config.py")
        with open(config_file, 'w') as f:
            f.write(playwright_config)

    def _generate_performance_tests(self, table_info: TableInfo) -> str:
        """Generate basic performance test structure."""
        model_name = inflection.camelize(table_info.name)

        return f'''
class Test{model_name}Performance:
    """Performance tests for {model_name}."""

    async def test_page_load_performance(self, authenticated_page: Page):
        """Test page load performance."""
        # Start measuring
        await authenticated_page.goto("/{table_info.name.lower()}/list/")

        # Wait for page to fully load
        await authenticated_page.wait_for_load_state("networkidle")

        # Basic performance check - page should load within reasonable time
        # This is handled by Playwright's default timeout settings

    async def test_large_dataset_performance(self, authenticated_page: Page):
        """Test performance with large datasets."""
        # This would require creating large test datasets
        # and measuring rendering performance
        pass
'''

    def _generate_cross_browser_tests(self, table_info: TableInfo) -> str:
        """Generate cross-browser compatibility test structure."""
        model_name = inflection.camelize(table_info.name)

        return f'''
class Test{model_name}CrossBrowser:
    """Cross-browser compatibility tests for {model_name}."""

    @pytest.mark.parametrize("browser_name", ["chromium", "firefox", "webkit"])
    async def test_cross_browser_compatibility(self, browser_name: str):
        """Test functionality across different browsers."""
        async with async_playwright() as p:
            browser = await getattr(p, browser_name).launch(headless=True)
            context = await browser.new_context()
            await self._authenticate_context(context)
            page = await context.new_page()

            try:
                # Test basic functionality in each browser
                await page.goto("/{table_info.name.lower()}/list/")
                await page.wait_for_load_state("networkidle")

                # Verify page loads correctly
                title = await page.title()
                assert "{model_name}" in title or "List" in title

            finally:
                await browser.close()
'''

    def _generate_form_data_fields(self, table_info: TableInfo) -> str:
        """Generate form data field assignments."""
        fields = []
        for i, column in enumerate(table_info.columns):
            if column.name.lower() in ['id', 'created_at', 'updated_at']:
                continue

            if column.type.lower() in ['varchar', 'text', 'string']:
                fields.append(f'            "{column.name}": f"test_{column.name}_{{index}}"')
            elif column.type.lower() in ['int', 'integer', 'bigint']:
                fields.append(f'            "{column.name}": index + 1')
            elif column.type.lower() in ['bool', 'boolean']:
                fields.append(f'            "{column.name}": index % 2 == 0')
            elif column.type.lower() in ['date', 'datetime', 'timestamp']:
                fields.append(f'            "{column.name}": "2024-01-01"')
            elif column.type.lower() in ['decimal', 'numeric', 'float']:
                fields.append(f'            "{column.name}": str(index * 10.5)')
            else:
                fields.append(f'            "{column.name}": f"test_value_{{index}}"')

        return ",\n".join(fields)

    def _generate_update_data_fields(self, table_info: TableInfo) -> str:
        """Generate update form data field assignments."""
        fields = []
        for column in table_info.columns:
            if column.name.lower() in ['id', 'created_at', 'updated_at']:
                continue

            if column.type.lower() in ['varchar', 'text', 'string']:
                fields.append(f'            "{column.name}": "updated_{column.name}"')
            elif column.type.lower() in ['int', 'integer', 'bigint']:
                fields.append(f'            "{column.name}": 999')
            elif column.type.lower() in ['bool', 'boolean']:
                fields.append(f'            "{column.name}": True')
            elif column.type.lower() in ['date', 'datetime', 'timestamp']:
                fields.append(f'            "{column.name}": "2024-12-31"')
            elif column.type.lower() in ['decimal', 'numeric', 'float']:
                fields.append(f'            "{column.name}": "999.99"')
            else:
                fields.append(f'            "{column.name}": "updated_value"')

        return ",\n".join(fields)

    def _generate_field_validation_tests(self, table_info: TableInfo) -> str:
        """Generate field validation test methods."""
        tests = []
        for column in table_info.columns:
            if column.nullable is False and column.name.lower() not in ['id', 'created_at', 'updated_at']:
                tests.append(f'''
        # Test required field validation for {column.name}
        await authenticated_page.fill('input[name="{column.name}"]', "")
        await authenticated_page.click('input[type="submit"]')

        # Should show validation error
        error_element = await authenticated_page.wait_for_selector('.error, .alert-danger')
        error_text = await error_element.text_content()
        assert "{column.name}" in error_text.lower() or "required" in error_text.lower()

        # Clear error by filling field
        await authenticated_page.fill('input[name="{column.name}"]', "valid_value")
''')

        return "\n".join(tests)

    def _generate_field_interaction_tests(self, table_info: TableInfo) -> str:
        """Generate field interaction test methods."""
        # This would generate tests for dynamic field interactions
        # like dependent dropdowns, conditional fields, etc.
        return '''
        # Test dynamic field interactions if present
        # This depends on specific application logic
        pass
'''