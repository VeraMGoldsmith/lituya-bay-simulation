"""Replay actual Mac-generated decks; these tests run no water solver."""
from pathlib import Path
import re
from zipfile import ZipFile

import pytest

from simulation import cap_comparison as cap
from simulation.common import ROOT, load

FIXTURE = ROOT / 'tests/fixtures/local_preflight_20261018/generated_decks.fixture'


@pytest.fixture
def real_decks(tmp_path):
    session = tmp_path / 'real_preflight'
    session.mkdir()
    with ZipFile(FIXTURE) as z:
        z.extractall(session)  # repository-owned regression fixture
    base, _ = cap.frozen_config()
    return session, base, load(session / 'inputs/setup.json')


def test_real_local_preflight_decks_pass_without_editing_any_input(real_decks):
    session, base, setup = real_decks
    before = {p.relative_to(session): p.read_bytes() for p in session.rglob('*') if p.is_file()}
    result = cap.verify_decks(session, base, setup)
    assert result['status'] == 'passed'
    assert [result['cases'][name]['speed_limit_m_s'] for name in cap.CASE_NAMES] == [50., 100., 200.]
    for name in cap.CASE_NAMES:
        assert result['cases'][name]['monitor'] == {
            'primary': 'expanded', 'points': {'legacy': 2491, 'expanded': 10318},
            'dt_check_s': 0., 'interp_method': 0}
    after = {p.relative_to(session): p.read_bytes() for p in session.rglob('*') if p.is_file()}
    assert before == after


def test_actual_padding_reproduces_previous_false_mismatch(real_decks):
    session, _, _ = real_decks
    texts = [(session/'cases'/name/'geoclaw.data').read_text() for name in cap.CASE_NAMES]
    old = [cap.SPEED_LINE.sub(lambda m: m[0][:m.start(1)-m.start()] + '<CAP>' +
            m[0][m.end(1)-m.start():], text) for text in texts]
    assert old[0] != old[1]
    assert old[1] == old[2]
    new = [cap.numerical_records(session/'cases'/name)[1] for name in cap.CASE_NAMES]
    assert new[0] == new[1] == new[2]


@pytest.mark.parametrize('token', ['100', '100.0', '+100.0', '1e2', '1.0D+02'])
def test_different_cap_spelling_and_alignment_is_numeric_only(real_decks, token):
    session, base, setup = real_decks
    p = session/'cases/cap_100/geoclaw.data'
    p.write_text(cap.SPEED_LINE.sub(f'{token:<20} =: {"speed_limit":<20}', p.read_text()))
    assert cap.verify_decks(session, base, setup)['cases']['cap_100']['speed_limit_m_s'] == 100.


@pytest.mark.parametrize('change', ['wrong_cap', 'missing_cap', 'duplicate_cap', 'gravity',
                                     'manning', 'dry_tolerance', 'config', 'monitor_time',
                                     'field_name', 'cap_comment', 'non_cap_spacing'])
def test_real_decks_still_reject_unapproved_changes(real_decks, change):
    session, base, setup = real_decks
    folder = session/'cases/cap_100'
    p = folder/'geoclaw.data'
    text = p.read_text()
    if change == 'wrong_cap':
        text = text.replace('100.0', '150.0')
    elif change == 'missing_cap':
        text = cap.SPEED_LINE.sub('', text)
    elif change == 'duplicate_cap':
        text += '\n100.0 =: speed_limit\n'
    elif change in {'gravity', 'manning', 'dry_tolerance'}:
        field = {'gravity': 'gravity', 'manning': 'manning_coefficient', 'dry_tolerance': 'dry_tolerance'}[change]
        text, count = re.subn(r'(?m)^.*=:\s*'+field+r'\b.*$', '999.0 =: '+field, text)
        assert count == 1
    elif change == 'field_name':
        text = text.replace('=: speed_limit', '=: speed_limit_typo')
    elif change == 'cap_comment':
        text = text.replace('=: speed_limit', '=: speed_limit # changed comment')
    elif change == 'non_cap_spacing':
        text = text.replace('=: gravity', '=:  gravity')
    elif change == 'config':
        q = folder/'config.json'
        q.write_text(q.read_text().replace('"travel_duration_s": 30.0', '"travel_duration_s": 18.0'))
        assert load(q) != cap.case_configs(base)['cap_100']
    else:
        q = folder/'fgmax_grids.data'
        # Mutate all monitor decks consistently: the explicit monitor check must reject it.
        old = q.read_text()
        new, count = re.subn(r'(?m)^.*# dt_check.*$', '0.2 # dt_check', old)
        assert count == 2
        for name in cap.CASE_NAMES:
            (session/'cases'/name/'fgmax_grids.data').write_text(new)
    p.write_text(text)
    with pytest.raises(cap.IntegrityError):
        cap.verify_decks(session, base, setup)
