"""
Tests for app.py business logic (Scenario 1: radio button auto-switch).
Uses object.__new__ to bypass CTk.__init__ and inject mock attributes,
so no display or GUI is needed.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Mock all GUI modules before importing app ──────────────────────────────────
_ctk_mock = MagicMock()
_tk_mock  = MagicMock()

# tk.IntVar needs real get/set behaviour — we replace it after import
sys.modules['customtkinter'] = _ctk_mock
sys.modules['tkinter']       = _tk_mock
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['api']           = MagicMock()
sys.modules['widgets']       = MagicMock()
sys.modules['desktop_client'] = MagicMock()

# Patch ctk.set_appearance_mode / set_default_color_theme (called at module level)
_ctk_mock.set_appearance_mode = MagicMock()
_ctk_mock.set_default_color_theme = MagicMock()
_ctk_mock.CTk = object   # App inherits from ctk.CTk → use plain object

sys.path.insert(0, str(Path(__file__).parent.parent))

# Patch the module-level ctk calls before App is defined
with patch.dict(sys.modules, {'customtkinter': _ctk_mock, 'tkinter': _tk_mock}):
    import app as app_module
    App = app_module.App


# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeIntVar:
    """Drop-in replacement for tk.IntVar without a Tk root."""
    def __init__(self, v: int = 0):
        self._v = v

    def get(self) -> int:
        return self._v

    def set(self, v: int) -> None:
        self._v = v


def make_app_full(chunks: list, sel: int = 0) -> App:
    """
    Like make_app but does NOT mock _render_registry_cards,
    so the real card-deduplication logic runs.
    """
    instance = object.__new__(App)
    instance.all_chunks           = chunks
    instance.selected_chunk_var   = FakeIntVar(sel)
    instance.groups               = {}
    instance.all_groups           = {}
    instance._canonical_indices   = {}
    instance._parent_sub_map      = {}
    instance.ttn_rows             = {}
    instance.done_reg_rows        = 0
    instance.all_reg_cards        = {}
    instance.distribute_btn       = MagicMock()
    instance.analyze_btn          = MagicMock()
    instance.analyze_all_btn      = MagicMock()
    instance._analyze_all_mode    = False
    instance.reg_list             = MagicMock()
    instance.reg_list.winfo_children.return_value = []
    instance._apply_sub_ttn_grouping = MagicMock()
    instance._status                 = MagicMock()
    # _render_registry_cards is intentionally NOT mocked
    return instance


def make_app(chunks: list, sel: int = 0) -> App:
    """
    Creates an App instance bypassing __init__, injecting only the attributes
    needed by _handle_analysis_done().
    """
    instance = object.__new__(App)
    instance.all_chunks           = chunks
    instance.selected_chunk_var   = FakeIntVar(sel)
    instance.groups               = {}
    instance.all_groups           = {}
    instance._canonical_indices   = {}
    instance._parent_sub_map      = {}
    instance.ttn_rows             = {}
    instance.done_reg_rows        = 0
    instance.all_reg_cards        = {}
    instance.distribute_btn       = MagicMock()
    instance.analyze_btn          = MagicMock()
    instance.analyze_all_btn      = MagicMock()
    instance._analyze_all_mode    = False
    instance.reg_list             = MagicMock()
    # Replace GUI-heavy helpers with no-ops
    instance._render_registry_cards  = MagicMock()
    instance._apply_sub_ttn_grouping = MagicMock()
    instance._status                 = MagicMock()
    return instance


def _mock_groups(names=('Registry1',)):
    """Build a minimal groups dict as expected by _handle_analysis_done."""
    return {
        (f'Sender{i}', f'WH{i}'): {
            'suggested_name': name,
            'ttns': [f'TTN{i}'],
            'doc_refs': [f'REF{i}'],
            'sender_description': 'Test Sender',
            'warehouse_description': 'Test WH',
        }
        for i, name in enumerate(names)
    }


# ── Scenario 1: auto-switch radio button after analysis ───────────────────────

class TestAutoSwitchAfterAnalysis:

    # ── With groups (valid TTNs found) ────────────────────────────────────────

    def test_groups_exist_and_next_chunk_available_switches(self):
        """After analysis with groups on chunk 0 of 2 → switch to chunk 1."""
        app = make_app(chunks=[['TTN1'], ['TTN2']], sel=0)
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        assert app.selected_chunk_var.get() == 1

    def test_groups_exist_middle_chunk_switches_to_next(self):
        """After analysis with groups on chunk 1 of 3 → switch to chunk 2."""
        app = make_app(chunks=[['A'], ['B'], ['C']], sel=1)
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        assert app.selected_chunk_var.get() == 2

    def test_groups_exist_last_chunk_stays(self):
        """After analysis with groups on the last chunk → do NOT switch (nothing to switch to)."""
        app = make_app(chunks=[['TTN1']], sel=0)
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        assert app.selected_chunk_var.get() == 0

    def test_groups_exist_last_of_three_stays(self):
        """Chunk 2 of 3 (last) with groups → stays on 2."""
        app = make_app(chunks=[['A'], ['B'], ['C']], sel=2)
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        assert app.selected_chunk_var.get() == 2

    # ── Without groups (no valid TTNs in chunk) ───────────────────────────────

    def test_no_groups_and_next_chunk_available_switches(self):
        """After analysis with no groups on chunk 0 of 2 → switch to chunk 1."""
        app = make_app(chunks=[['TTN1'], ['TTN2']], sel=0)
        App._handle_analysis_done(app, {}, {}, {})
        assert app.selected_chunk_var.get() == 1

    def test_no_groups_last_chunk_resets_to_zero(self):
        """After analysis with no groups on the last chunk → reset to chunk 0."""
        app = make_app(chunks=[['TTN1'], ['TTN2']], sel=1)
        App._handle_analysis_done(app, {}, {}, {})
        assert app.selected_chunk_var.get() == 0

    def test_no_groups_single_chunk_resets_to_zero(self):
        """Single chunk, no groups → stays at 0 (reset to 0)."""
        app = make_app(chunks=[['TTN1']], sel=0)
        App._handle_analysis_done(app, {}, {}, {})
        assert app.selected_chunk_var.get() == 0

    # ── Analyze button is always re-enabled ───────────────────────────────────

    def test_analyze_btn_reenabled_with_groups(self):
        app = make_app(chunks=[['A'], ['B']], sel=0)
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        app.analyze_btn.configure.assert_called()

    def test_analyze_btn_reenabled_without_groups(self):
        app = make_app(chunks=[['A'], ['B']], sel=0)
        App._handle_analysis_done(app, {}, {}, {})
        app.analyze_btn.configure.assert_called()

    # ── Distribute button state ───────────────────────────────────────────────

    def test_distribute_btn_enabled_when_groups_exist(self):
        app = make_app(chunks=[['A']], sel=0)
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        app.distribute_btn.configure.assert_called_with(state='normal')

    def test_distribute_btn_disabled_when_no_groups(self):
        app = make_app(chunks=[['A']], sel=0)
        App._handle_analysis_done(app, {}, {}, {})
        app.distribute_btn.configure.assert_called_with(state='disabled')

    def test_distribute_btn_stays_enabled_when_later_chunk_has_no_groups(self):
        """Bug regression: analyzing a chunk with no valid TTNs must NOT disable the
        button if earlier chunks already produced groups in all_groups."""
        app = make_app(chunks=[['A'], ['B'], ['C']], sel=0)
        # Portion 0: valid TTNs → all_groups populated
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        app.distribute_btn.configure.reset_mock()
        # Portion 1: no valid TTNs (duplicate / already_in_registry / not_found)
        app.selected_chunk_var.set(1)
        App._handle_analysis_done(app, {}, {}, {})
        # Button must still be enabled because all_groups is not empty
        app.distribute_btn.configure.assert_called_with(state='normal')


# ── No duplicate registry cards on repeated analysis ─────────────────────────

def _groups(name='Registry1', ttns=('TTN1',), sender='S1', wh='W1'):
    ttn_list = list(ttns)
    return {(sender, wh): {
        'suggested_name': name,
        'ttns': ttn_list,
        'doc_refs': [f'REF_{t}' for t in ttn_list],
        'sender_description': 'Test Sender',
        'warehouse_description': 'Test WH',
    }}


class TestNoRegistryCardDuplicates:
    """
    Verifies that repeated analysis calls do not create duplicate cards
    in the registry column (all_reg_cards dict deduplicates by name).
    """

    def test_same_group_analyzed_twice_creates_one_card(self):
        """Two analysis runs with the same registry name → only 1 card in all_reg_cards."""
        app = make_app_full(chunks=[['TTN1'], ['TTN2']], sel=0)
        groups = _groups()

        App._handle_analysis_done(app, groups, {}, {})
        assert len(app.all_reg_cards) == 1

        app.selected_chunk_var.set(0)
        App._handle_analysis_done(app, groups, {}, {})
        assert len(app.all_reg_cards) == 1  # still 1, not 2

    def test_same_group_analyzed_ten_times_creates_one_card(self):
        """Stress: 10 repeated analyses → still exactly 1 card."""
        app = make_app_full(chunks=[['TTN1']], sel=0)
        groups = _groups()

        for _ in range(10):
            app.selected_chunk_var.set(0)
            App._handle_analysis_done(app, groups, {}, {})

        assert len(app.all_reg_cards) == 1

    def test_different_group_names_create_separate_cards(self):
        """Two distinct registry names → 2 separate cards, no merging."""
        app = make_app_full(chunks=[['TTN1'], ['TTN2'], ['TTN3']], sel=0)

        App._handle_analysis_done(app, _groups('Reg1', ['TTN1'], 'S1', 'W1'), {}, {})
        assert len(app.all_reg_cards) == 1

        app.selected_chunk_var.set(1)
        App._handle_analysis_done(app, _groups('Reg2', ['TTN2'], 'S2', 'W2'), {}, {})
        assert len(app.all_reg_cards) == 2

    def test_card_names_match_group_names(self):
        """Keys in all_reg_cards must equal the suggested_name of each group."""
        app = make_app_full(chunks=[['TTN1'], ['TTN2']], sel=0)

        App._handle_analysis_done(app, _groups('MyRegistry'), {}, {})
        assert 'MyRegistry' in app.all_reg_cards

    def test_existing_card_updated_not_replaced(self):
        """On re-analysis, the existing card object is reused (update_count called, not add_ttns_pending)."""
        app = make_app_full(chunks=[['TTN1'], ['TTN2']], sel=0)
        groups = _groups()

        App._handle_analysis_done(app, groups, {}, {})
        original_card = app.all_reg_cards['Registry1']

        app.selected_chunk_var.set(0)
        App._handle_analysis_done(app, groups, {}, {})

        assert app.all_reg_cards['Registry1'] is original_card
        original_card.update_count.assert_called()

    def test_reanalysis_count_stays_correct(self):
        """Re-analyzing the same portion must NOT increment the card count."""
        app = make_app_full(chunks=[['TTN1'], ['TTN2']], sel=0)
        groups = _groups(ttns=['TTN1'])

        App._handle_analysis_done(app, groups, {}, {})
        # Simulate re-analysis of same portion
        app.selected_chunk_var.set(0)
        App._handle_analysis_done(app, groups, {}, {})

        card = app.all_reg_cards['Registry1']
        # update_count should have been called with 1 (not 2) on re-analysis
        card.update_count.assert_called_with(1)

    def test_two_portions_same_registry_accumulates_correctly(self):
        """Two portions with different TTNs for the same registry → merged total in all_groups."""
        app = make_app_full(chunks=[['TTN1'], ['TTN2'], ['TTN3']], sel=0)

        # Portion 0: TTN1 for Registry1
        App._handle_analysis_done(app, _groups('Registry1', ['TTN1']), {}, {})
        # Portion 1: TTN2 for the same Registry1
        app.selected_chunk_var.set(1)
        App._handle_analysis_done(app, _groups('Registry1', ['TTN2'], 'S1', 'W1'), {}, {})

        key = ('S1', 'W1')
        assert set(app.all_groups[key]['ttns']) == {'TTN1', 'TTN2'}
        # Card updated with merged total = 2
        app.all_reg_cards['Registry1'].update_count.assert_called_with(2)


# ── Analyze-all mode ──────────────────────────────────────────────────────────

def make_app_for_analyze_all(chunks: list, sel: int = 0) -> App:
    """make_app extended with after() and _analyze() mocks for analyze-all tests."""
    instance = make_app(chunks=chunks, sel=sel)
    instance.after    = MagicMock()
    instance._analyze = MagicMock()
    return instance


class TestAnalyzeAll:
    """Tests for _analyze_all() toggle and auto-loop in _handle_analysis_done."""

    # ── _analyze_all() toggle ─────────────────────────────────────────────────

    def test_first_call_activates_mode(self):
        """First press: _analyze_all_mode becomes True."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']])
        App._analyze_all(app)
        assert app._analyze_all_mode is True

    def test_first_call_changes_button_text(self):
        """First press: button text changes to 'Зупинити'."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']])
        App._analyze_all(app)
        app.analyze_all_btn.configure.assert_called_with(text="Зупинити")

    def test_first_call_triggers_analyze(self):
        """First press: _analyze() is called to start the first portion."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']])
        App._analyze_all(app)
        app._analyze.assert_called_once()

    def test_second_call_deactivates_mode(self):
        """Pressing 'Зупинити': _analyze_all_mode becomes False."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']])
        app._analyze_all_mode = True
        App._analyze_all(app)
        assert app._analyze_all_mode is False

    def test_second_call_restores_button_text(self):
        """Pressing 'Зупинити': button text restored to 'Аналізувати все'."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']])
        app._analyze_all_mode = True
        App._analyze_all(app)
        app.analyze_all_btn.configure.assert_called_with(text="Аналізувати все")

    def test_second_call_does_not_trigger_analyze(self):
        """Pressing 'Зупинити': _analyze() is NOT called."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']])
        app._analyze_all_mode = True
        App._analyze_all(app)
        app._analyze.assert_not_called()

    # ── Auto-loop: no groups ──────────────────────────────────────────────────

    def test_no_groups_next_chunk_triggers_after(self):
        """analyze_all mode + no groups + next chunk → after() scheduled."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, {}, {}, {})
        app.after.assert_called_once()

    def test_no_groups_next_chunk_after_calls_analyze(self):
        """The callable passed to after() is _analyze."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, {}, {}, {})
        _, callback = app.after.call_args[0]
        assert callback is app._analyze

    def test_no_groups_last_chunk_stops_mode(self):
        """analyze_all mode + no groups + last chunk → mode deactivated."""
        app = make_app_for_analyze_all(chunks=[['A']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, {}, {}, {})
        assert app._analyze_all_mode is False

    def test_no_groups_last_chunk_restores_button(self):
        """analyze_all mode + no groups + last chunk → button text restored."""
        app = make_app_for_analyze_all(chunks=[['A']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, {}, {}, {})
        app.analyze_all_btn.configure.assert_called_with(text="Аналізувати все")

    def test_no_groups_last_chunk_no_after_call(self):
        """analyze_all mode + no groups + last chunk → after() NOT called."""
        app = make_app_for_analyze_all(chunks=[['A']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, {}, {}, {})
        app.after.assert_not_called()

    # ── Auto-loop: with groups ────────────────────────────────────────────────

    def test_groups_next_chunk_triggers_after(self):
        """analyze_all mode + groups + next chunk available → after() scheduled."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        app.after.assert_called_once()

    def test_groups_next_chunk_after_calls_analyze(self):
        """analyze_all mode + groups + next chunk → after() callback is _analyze."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        _, callback = app.after.call_args[0]
        assert callback is app._analyze

    def test_groups_last_chunk_stops_mode(self):
        """analyze_all mode + groups + last chunk → mode deactivated."""
        app = make_app_for_analyze_all(chunks=[['A']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        assert app._analyze_all_mode is False

    def test_groups_last_chunk_restores_button(self):
        """analyze_all mode + groups + last chunk → button text restored."""
        app = make_app_for_analyze_all(chunks=[['A']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        app.analyze_all_btn.configure.assert_called_with(text="Аналізувати все")

    def test_groups_last_chunk_no_after_call(self):
        """analyze_all mode + groups + last chunk → after() NOT called."""
        app = make_app_for_analyze_all(chunks=[['A']], sel=0)
        app._analyze_all_mode = True
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        app.after.assert_not_called()

    # ── Mode off (default) → no auto-loop ────────────────────────────────────

    def test_mode_off_no_after_call_with_groups(self):
        """Normal mode (not analyze-all) → after() never called even with next chunk."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']], sel=0)
        # _analyze_all_mode is False by default
        App._handle_analysis_done(app, _mock_groups(), {}, {})
        app.after.assert_not_called()

    def test_mode_off_no_after_call_without_groups(self):
        """Normal mode (not analyze-all) → after() never called even with next chunk."""
        app = make_app_for_analyze_all(chunks=[['A'], ['B']], sel=0)
        App._handle_analysis_done(app, {}, {}, {})
        app.after.assert_not_called()
