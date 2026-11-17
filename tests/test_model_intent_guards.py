from unittest.mock import patch
import pytest
from kiwi_litchi.common import UserError
from kiwi_litchi.db import Store
from kiwi_litchi.demo import seed
from kiwi_litchi.intelligence import model_intent

@pytest.fixture
def books(tmp_path):
    store=Store(tmp_path/'data');seed(store);return store

EXPECTED={'ledger':'Mehta Hardware','measure':'payments','start':'2026-04-01','end':'2027-03-31'}
QUESTION='payments to Mehta Hardware in FY 2026-27'

@pytest.mark.parametrize('change',[
    {'ledger':'Cash'},
    {'ledger':'Unrecognised supplier'},
    {'measure':'receipts'},
    {'measure':'all'},
    {'end':'2026-03-31'},
    {'start':'2025-04-01','end':'2026-03-31'},
    {'start':'2026-02-30'},
])
def test_model_must_not_change_explicit_book_question(books,change):
    with patch('kiwi_litchi.intelligence.Ollama') as model:
        model.return_value.structured.return_value=dict(EXPECTED,**change)
        with pytest.raises(UserError):model_intent(books,'demo',QUESTION)


def test_matching_actual_model_answer_is_returned(books):
    with patch('kiwi_litchi.intelligence.Ollama') as model:
        model.return_value.structured.return_value=EXPECTED
        assert model_intent(books,'demo',QUESTION)==EXPECTED
        assert model.return_value.structured.call_count==1
