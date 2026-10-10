PY ?= python
N ?= 0

.PHONY: contracts unit accept test lint fmt ingest synth features train fleet pipeline demo report api stub all

contracts:
	$(PY) -m pytest tests/acceptance/test_00_contracts.py -q

unit:
	$(PY) -m pytest tests/unit -q

accept:
	$(PY) -m pytest tests/acceptance -q -k "test_0$(N)_" -rs

test: contracts unit

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

fmt:
	ruff format src tests scripts
	ruff check --fix src tests scripts

ingest:
	$(PY) -m divas_air.ingest --source all

synth:
	$(PY) -m divas_air.synth --seed 42
	$(PY) -m divas_air.synth.demo

features:
	$(PY) -m divas_air.features --source all
	$(PY) -m divas_air.features --calibrate

train:
	$(PY) -m divas_air.models.train
	$(PY) -m divas_air.features --calibrate

fleet:
	$(PY) -m divas_air.fleet --source baltic --profile regional
	$(PY) -m divas_air.fleet --source control --profile regional
	$(PY) -m divas_air.fleet --static-halos

pipeline:
	$(PY) -m divas_air.pipeline --source all

demo:
	$(PY) -m divas_air.api.replay

report:
	$(PY) -m divas_air.eval.report

api:
	uvicorn divas_air.api.app:app --port 8000

stub:
	uvicorn scripts.stub_api:app --port 8000 --reload

all: ingest synth features train fleet pipeline demo report
