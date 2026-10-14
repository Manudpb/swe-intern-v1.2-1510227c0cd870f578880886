"""Accuracy acceptance checks; rejected/malformed/failed positive cases score zero."""
import json
import math
from pathlib import Path
from statistics import median
from time import perf_counter
import requests
import pytest
from conftest import submit_claim, image_for

SEVERITY_ORDINAL = {'minor': 0, 'moderate': 1, 'severe': 2, 'catastrophic': 3}

def severity_score(predicted, expected):
    if predicted not in SEVERITY_ORDINAL or expected not in SEVERITY_ORDINAL: return 0.0
    distance = abs(SEVERITY_ORDINAL[predicted] - SEVERITY_ORDINAL[expected])
    return 1.0 if distance == 0 else (0.5 if distance == 1 else 0.0)

def cost_score(predicted_min, predicted_max, expected_min, expected_max):
    values = (predicted_min, predicted_max, expected_min, expected_max)
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values): return 0.0
    if predicted_min < 0 or predicted_max < predicted_min: return 0.0
    expected = (expected_min + expected_max) / 2
    predicted = (predicted_min + predicted_max) / 2
    return max(0.0, 1 - abs(predicted - expected) / expected) if expected else float(predicted == 0)

def collect_results(api_url, images, truths, submit=submit_claim, progress=None):
    results = {}
    for image_id, gt in truths.items():
        if not gt.get('damage_type'): continue  # negatives belong to intake validation
        path = image_for(images, image_id)  # missing employer fixture is an error, never a skipped case
        result = {'ground_truth': gt, 'prediction': {}, 'status': 'failed'}
        results[image_id] = result
        started = perf_counter()
        try:
            response = submit(api_url, path, description=gt.get('description_hint'), policy_type=gt.get('policy_type'))
            result['http_status'] = response.status_code
            if response.status_code in (200, 201):
                payload = response.json()
                if isinstance(payload, dict):
                    result.update(prediction=payload, status='returned')
        except (requests.RequestException, ValueError) as exc:
            result['error'] = type(exc).__name__
        finally:
            result['duration_ms'] = round((perf_counter() - started) * 1000, 1)
        print(f"Accuracy {len(results)}: {image_id} {result['status']} in {result['duration_ms']} ms", flush=True)
        if progress:
            progress(results)
    assert results, 'No positive evaluation cases supplied'
    return results

def smoke_cases(truths):
    selected, types = {}, set()
    for case_id, truth in sorted(truths.items()):
        damage = truth.get('damage_type')
        if damage and damage not in types:
            selected[case_id] = truth
            types.add(damage)
        if len(selected) == 3:
            break
    return selected


def write_measurements(path, results, expected, mode):
    durations = [r['duration_ms'] for r in results.values()]
    returned = [r['duration_ms'] for r in results.values() if r['status'] == 'returned']
    report = {
        'mode': mode, 'complete': len(results) == expected,
        'attempted': len(results), 'expected': expected,
        'returned': len(returned), 'failed': len(results) - len(returned),
        'p50_attempt_ms': median(durations) if durations else None,
        'p50_returned_ms': median(returned) if returned else None,
        'metrics': metrics(results) if results else None,
        'note': 'Client end-to-end timings include application, models, tools and network. Smoke is not a full grade.',
        'cases': {k: {f: v for f, v in r.items() if f not in ('prediction', 'ground_truth')} for k, r in results.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


@pytest.fixture(scope='session')
def triage_results(api_url, test_images_dir, ground_truth_files, request):
    smoke = request.config.getoption('--accuracy-smoke')
    truths = smoke_cases(ground_truth_files) if smoke else ground_truth_files
    expected = sum(bool(t.get('damage_type')) for t in truths.values())
    mode = 'smoke' if smoke else 'full'
    path = Path(__file__).resolve().parents[1] / 'results' / f'accuracy_{mode}.json'
    def progress(results):
        write_measurements(path, results, expected, mode)
    progress({})
    print(f'Accuracy {mode}: {expected} sequential triages; timings saved after each case to {path}', flush=True)
    return collect_results(api_url, test_images_dir, truths, progress=progress)


def assessment(data):
    value = data['prediction'].get('triage_assessment')
    return value if isinstance(value, dict) else {}

def metrics(results):
    damage, severity, costs = [], [], []
    for data in results.values():
        gt, pred = data['ground_truth'], assessment(data)
        damage.append(float(pred.get('damage_type') == gt['damage_type']))
        severity.append(severity_score(pred.get('severity'), gt['severity']))
        cost = pred.get('estimated_repair_cost') or {}
        if not isinstance(cost, dict): cost = {}
        expected = gt['estimated_repair_cost']
        costs.append(cost_score(cost.get('min'), cost.get('max'), expected['min'], expected['max']))
    return {k: sum(v) / len(v) for k, v in [('damage', damage), ('severity', severity), ('cost', costs)]}

class TestAccuracy:
    def test_damage_type_accuracy(self, triage_results, record_property):
        score = metrics(triage_results)['damage']
        record_property('damage_type_accuracy', score)
        assert score >= 0.5, f'Damage accuracy {score:.1%}; all {len(triage_results)} positive cases included'

    def test_severity_accuracy(self, triage_results, record_property):
        score = metrics(triage_results)['severity']
        record_property('severity_score', score)
        assert score >= 0.4

    def test_cost_estimate_accuracy(self, triage_results, record_property):
        score = metrics(triage_results)['cost']
        record_property('cost_score', score)
        assert score >= 0.3

    def test_recommendation_not_empty(self, triage_results):
        for case_id, data in triage_results.items():
            value = assessment(data).get('recommendation')
            assert isinstance(value, str) and len(value.strip()) > 20, case_id

    def test_output_schema_valid(self, triage_results):
        required = {'damage_type', 'severity', 'affected_areas', 'damage_description', 'estimated_repair_cost', 'urgency', 'recommendation', 'similar_past_claims'}
        for case_id, data in triage_results.items():
            pred = assessment(data)
            assert required <= pred.keys(), case_id
            assert pred['urgency'] in ('low', 'medium', 'high', 'critical'), case_id
