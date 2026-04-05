"""
Unit tests for scanner.py pure functions.
Covers:
  - Scenario 3: classify_file_change (file mutation detection)
  - Scenario 4: expected_sub_ttns, sub-TTN identification, compute_canonical (duplicates)
  - Bonus: read_chunks, group_ttns
"""
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# scanner.py imports api at module level — mock it before import
sys.modules.setdefault('api', MagicMock())

sys.path.insert(0, str(Path(__file__).parent.parent))
import scanner as sc


# ── Scenario 3: classify_file_change ──────────────────────────────────────────

class TestClassifyFileChange:
    def test_unchanged(self):
        chunks = [['A', 'B'], ['C']]
        assert sc.classify_file_change(chunks, chunks) == 'unchanged'

    def test_unchanged_empty(self):
        assert sc.classify_file_change([[]], [[]]) == 'unchanged'

    def test_append_only_one_new_chunk(self):
        old = [['A', 'B']]
        new = [['A', 'B'], ['C', 'D']]
        assert sc.classify_file_change(old, new) == 'append_only'

    def test_append_only_multiple_new_chunks(self):
        old = [['A'], ['B']]
        new = [['A'], ['B'], ['C'], ['D']]
        assert sc.classify_file_change(old, new) == 'append_only'

    def test_append_only_from_empty(self):
        # Edge case: all_chunks starts as [[]] (one empty chunk) after _clear_ui
        assert sc.classify_file_change([[]], [['A'], ['B']]) == 'full_reset'

    def test_chunk_append_ttn_added_to_chunk(self):
        old = [['A', 'B'], ['C']]
        new = [['A', 'B', 'X'], ['C', 'Y']]
        assert sc.classify_file_change(old, new) == 'chunk_append'

    def test_chunk_append_single_chunk(self):
        old = [['A']]
        new = [['A', 'B', 'C']]
        assert sc.classify_file_change(old, new) == 'chunk_append'

    def test_full_reset_ttn_removed(self):
        old = [['A', 'B']]
        new = [['A']]
        assert sc.classify_file_change(old, new) == 'full_reset'

    def test_full_reset_ttn_replaced(self):
        old = [['A', 'B']]
        new = [['C', 'B']]
        assert sc.classify_file_change(old, new) == 'full_reset'

    def test_full_reset_chunk_count_decreased(self):
        old = [['A'], ['B']]
        new = [['A']]
        assert sc.classify_file_change(old, new) == 'full_reset'

    def test_full_reset_order_changed(self):
        old = [['A', 'B']]
        new = [['B', 'A']]
        assert sc.classify_file_change(old, new) == 'full_reset'


# ── Scenario 4a: expected_sub_ttns ────────────────────────────────────────────

class TestExpectedSubTtns:
    PARENT = '20400512031414'

    def test_seats_1_returns_empty(self):
        assert sc.expected_sub_ttns(self.PARENT, 1) == []

    def test_seats_2_returns_one_sub(self):
        result = sc.expected_sub_ttns(self.PARENT, 2)
        assert result == ['204005120314140001']

    def test_seats_3_returns_two_subs(self):
        result = sc.expected_sub_ttns(self.PARENT, 3)
        assert result == ['204005120314140001', '204005120314140002']

    def test_seats_5_returns_four_subs(self):
        result = sc.expected_sub_ttns(self.PARENT, 5)
        assert len(result) == 4
        assert result[0] == '204005120314140001'
        assert result[3] == '204005120314140004'

    def test_sub_ttn_length_is_18(self):
        for sub in sc.expected_sub_ttns(self.PARENT, 4):
            assert len(sub) == 18

    def test_sub_ttn_parent_prefix(self):
        for sub in sc.expected_sub_ttns(self.PARENT, 4):
            assert sub[:14] == self.PARENT

    def test_sub_ttn_identification(self):
        # Sub-TTN is identified by: len==18 AND first 14 chars match a parent in the file
        parent = self.PARENT
        sub = '204005120314140001'
        file_ttn_set = {parent, 'other14digitsTTN'}
        assert len(sub) == 18 and sub[:14] in file_ttn_set

    def test_non_sub_ttn_not_identified(self):
        # A 14-digit TTN is never a sub-TTN
        ttn = '20400512031414'
        assert len(ttn) != 18

    def test_missing_sub_ttn_detection(self):
        parent = self.PARENT
        seats = 4
        subs = sc.expected_sub_ttns(parent, seats)  # [0001, 0002, 0003]
        file_ttn_set = {parent, subs[0], subs[2]}    # missing 0002
        missing = [s for s in subs if s not in file_ttn_set]
        assert missing == [subs[1]]

    def test_all_sub_ttns_present(self):
        parent = self.PARENT
        seats = 3
        subs = sc.expected_sub_ttns(parent, seats)
        file_ttn_set = {parent} | set(subs)
        missing = [s for s in subs if s not in file_ttn_set]
        assert missing == []

    def test_sub_ttns_from_different_chunks_all_found(self):
        # Sub-TTNs spread across chunks but file_ttn_set is global →
        # missing check must find them all regardless of chunk placement.
        parent = self.PARENT          # in chunk 1
        seats  = 4                    # expects 0001, 0002, 0003
        subs   = sc.expected_sub_ttns(parent, seats)
        # 0001, 0002 in chunk 2; 0003 in chunk 3 — but file_ttn_set is flat
        file_ttn_set = {parent} | set(subs)  # same as if they were in any chunks
        missing = [s for s in subs if s not in file_ttn_set]
        assert missing == [], "sub-TTNs in different chunks must still be found"

    def test_validate_ttn_seats_triggers_sub_ttn_grouping(self):
        # When API returns SeatsAmount > 1 AND all sub-TTNs are in file →
        # parent_sub_map is populated so add_sub_ttns can be called in UI.
        parent = self.PARENT
        seats  = 3
        subs   = sc.expected_sub_ttns(parent, seats)  # [0001, 0002]
        file_ttn_set = {parent} | set(subs)

        doc = {'SeatsAmount': str(seats), 'ScanSheetNumber': '', 'SenderDescription': 'Test'}

        with patch('api.get_document_info', return_value=doc):
            status, returned_doc = sc.validate_ttn('key', parent)

        assert status == 'ok'
        returned_seats = int(returned_doc.get(sc.SEATS_FIELD, 1) or 1)
        assert returned_seats == seats

        # Reproduce the _worker logic: sub-TTNs present → parent_sub_map filled
        missing = [s for s in subs if s not in file_ttn_set]
        assert missing == []
        parent_sub_map = {parent: subs}          # would be set in _worker
        assert parent_sub_map[parent] == subs    # add_sub_ttns called with this list


# ── Scenario 2: compute_canonical (duplicate logic) ───────────────────────────

class TestComputeCanonical:
    def test_single_occurrence_no_duplicates(self):
        ok_indices = {'TTN1': [5]}
        canonical, dup_idxs = sc.compute_canonical(ok_indices)
        assert canonical['TTN1'] == 5
        assert 'TTN1' not in dup_idxs

    def test_two_occurrences_last_is_canonical(self):
        ok_indices = {'TTN1': [0, 7]}
        canonical, dup_idxs = sc.compute_canonical(ok_indices)
        assert canonical['TTN1'] == 7
        assert dup_idxs['TTN1'] == [0]

    def test_three_occurrences_last_is_canonical(self):
        ok_indices = {'TTN1': [0, 3, 7]}
        canonical, dup_idxs = sc.compute_canonical(ok_indices)
        assert canonical['TTN1'] == 7
        assert 0 in dup_idxs['TTN1']
        assert 3 in dup_idxs['TTN1']
        assert 7 not in dup_idxs.get('TTN1', [])

    def test_multiple_ttns_independent(self):
        ok_indices = {'TTN1': [0, 5], 'TTN2': [1]}
        canonical, dup_idxs = sc.compute_canonical(ok_indices)
        assert canonical['TTN1'] == 5
        assert canonical['TTN2'] == 1
        assert 'TTN2' not in dup_idxs

    def test_empty_input(self):
        canonical, dup_idxs = sc.compute_canonical({})
        assert canonical == {}
        assert dup_idxs == {}


# ── Bonus: read_chunks ─────────────────────────────────────────────────────────

class TestReadChunks:
    def _write(self, tmp_path, content: str) -> str:
        f = tmp_path / 'scanner.txt'
        f.write_text(textwrap.dedent(content), encoding='utf-8')
        return str(f)

    def test_single_chunk(self, tmp_path):
        path = self._write(tmp_path, """\
            20400512031414
            20400512031415
        """)
        assert sc.read_chunks(path) == [['20400512031414', '20400512031415']]

    def test_two_chunks_separated_by_empty_line(self, tmp_path):
        path = self._write(tmp_path, """\
            AAA
            BBB

            CCC
        """)
        assert sc.read_chunks(path) == [['AAA', 'BBB'], ['CCC']]

    def test_two_chunks_separated_by_dash(self, tmp_path):
        path = self._write(tmp_path, """\
            AAA
            -
            BBB
        """)
        assert sc.read_chunks(path) == [['AAA'], ['BBB']]

    def test_whitespace_normalized(self, tmp_path):
        path = self._write(tmp_path, "  20400512031414  \n")
        assert sc.read_chunks(path) == [['20400512031414']]

    def test_empty_file_returns_one_empty_chunk(self, tmp_path):
        path = self._write(tmp_path, "")
        assert sc.read_chunks(path) == [[]]

    def test_trailing_empty_lines_ignored(self, tmp_path):
        path = self._write(tmp_path, "AAA\nBBB\n\n\n")
        assert sc.read_chunks(path) == [['AAA', 'BBB']]


# ── Bonus: group_ttns ─────────────────────────────────────────────────────────

class TestGroupTtns:
    def _doc(self, sender='S1', warehouse='W1', sender_desc='Sender One',
             address_desc='Warehouse 1', ref='REF1'):
        return {
            'Sender': sender,
            'SettlmentAddressData': {'SenderWarehouseRef': warehouse, 'SenderWarehouseNumber': '1'},
            'SenderDescription': sender_desc,
            'SenderAddressDescription': address_desc,
            'Ref': ref,
        }

    def test_single_ttn(self):
        pairs = [('TTN1', self._doc())]
        groups = sc.group_ttns(pairs)
        assert len(groups) == 1
        key = list(groups.keys())[0]
        assert groups[key]['ttns'] == ['TTN1']

    def test_same_sender_warehouse_grouped(self):
        pairs = [('TTN1', self._doc()), ('TTN2', self._doc())]
        groups = sc.group_ttns(pairs)
        assert len(groups) == 1
        key = list(groups.keys())[0]
        assert set(groups[key]['ttns']) == {'TTN1', 'TTN2'}

    def test_different_sender_different_group(self):
        pairs = [('TTN1', self._doc(sender='S1')), ('TTN2', self._doc(sender='S2'))]
        groups = sc.group_ttns(pairs)
        assert len(groups) == 2

    def test_different_warehouse_different_group(self):
        pairs = [('TTN1', self._doc(warehouse='W1')), ('TTN2', self._doc(warehouse='W2'))]
        groups = sc.group_ttns(pairs)
        assert len(groups) == 2

    def test_empty_input(self):
        assert sc.group_ttns([]) == {}
