"""Small consistency checks; these do not prove model execution or authorship."""
import math


def validate_trace(trace, assessment, cost_table, knowledge_base):
    steps = trace.get('steps')
    assert isinstance(steps, list) and steps, 'Missing trace steps'
    outputs = {}
    retrieved_ids = set()
    pending = None
    for step in steps:
        kind = step.get('type')
        assert kind in ('reason', 'act', 'observe'), 'Unknown trace event'
        assert isinstance(step.get('content'), str) and step['content'].strip(), 'Empty event description'
        if kind == 'act':
            assert pending is None, 'Previous action has no observation'
            name = step.get('tool_name')
            assert isinstance(name, str) and name.strip(), 'Missing tool name'
            arguments = step.get('tool_input')
            assert isinstance(arguments, dict) and arguments, 'Missing tool inputs'
            pending = (name, arguments)
        elif kind == 'observe':
            assert pending is not None, 'Observation has no action'
            output = step.get('tool_output')
            assert isinstance(output, (dict, list)) and output, 'Missing substantive tool output'
            name, arguments = pending
            pending = None
            if isinstance(output, dict) and output.get('error'):
                continue  # a recorded tool failure is allowed; require successful evidence below
            if name == 'estimate_repair_cost':
                assert isinstance(output, dict), 'Cost output must be an object'
                row = cost_table['cost_matrix'].get(arguments.get('damage_type'), {}).get(arguments.get('severity'))
                assert row, 'Invalid cost inputs'
                areas = arguments.get('affected_areas')
                assert isinstance(areas, list) and all(isinstance(a, str) and a.strip() for a in areas)
                count = max(1, len(set(a.strip().lower() for a in areas)))
                for field in ('min', 'max'):
                    value = output.get(field)
                    assert isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
                    assert value == row[field + '_per_area'] * count, 'Cost observation contradicts the supplied table'
            elif name == 'search_past_claims':
                assert isinstance(arguments.get('query'), str) and arguments['query'].strip()
                records = output.get('claims') if isinstance(output, dict) else output
                assert isinstance(records, list) and records, 'No retrieved claim evidence'
                assert all(isinstance(r, dict) and r.get('claim_id') in knowledge_base for r in records), 'Unknown retrieved claim ID'
                retrieved_ids.update(r['claim_id'] for r in records)
            outputs[name] = (arguments, output)
    assert pending is None, 'Last action has no observation'
    assert 'estimate_repair_cost' in outputs and 'search_past_claims' in outputs, 'Missing successful cost/retrieval evidence'
    arguments, cost = outputs['estimate_repair_cost']
    for field in ('damage_type', 'severity', 'affected_areas'):
        assert arguments[field] == assessment.get(field), 'Final scope differs from latest cost inputs'
    assert all(assessment.get('estimated_repair_cost', {}).get(k) == cost[k] for k in ('min', 'max')), 'Report cost differs from trace'
    citations = assessment.get('similar_past_claims')
    assert isinstance(citations, list) and citations, 'Report has no citations'
    assert all(isinstance(c, dict) and c.get('claim_id') in retrieved_ids for c in citations), 'Report cites records absent from successful retrievals'
