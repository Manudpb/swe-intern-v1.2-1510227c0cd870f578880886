// Two small jobs: keep the submit button honest while a request is in flight, and fill the
// trace panel. The fetch is same-origin against the UI's own proxy path, so there is no CORS.
(function () {
  var form = document.getElementById('claim-form');
  if (form) {
    form.addEventListener('submit', function () {
      var button = document.getElementById('submit-button');
      var pending = document.getElementById('pending');
      if (button) { button.disabled = true; button.textContent = 'Assessing…'; }
      if (pending) { pending.hidden = false; }
    });
  }

  var panel = document.getElementById('trace-panel');
  if (!panel) { return; }
  var claimId = panel.getAttribute('data-claim-id');
  var list = document.getElementById('trace-steps');
  // The API prefix lives on the form, so the page and the script cannot disagree about it.
  var apiBase = (form && form.getAttribute('data-api-base')) || '/api/v1';

  fetch(apiBase + '/agent/trace/' + encodeURIComponent(claimId))
    .then(function (response) {
      if (!response.ok) { throw new Error('HTTP ' + response.status); }
      return response.json();
    })
    .then(function (trace) {
      list.innerHTML = '';
      (trace.steps || []).forEach(function (step) {
        var item = document.createElement('li');
        var kind = document.createElement('span');
        kind.className = 'step-kind ' + step.type;
        kind.textContent = step.type;
        item.appendChild(kind);
        item.appendChild(document.createTextNode(step.content));
        if (step.tool_name) {
          item.appendChild(renderBlock('input to ' + step.tool_name, step.tool_input));
        }
        if (step.tool_output) {
          item.appendChild(renderBlock('observed', step.tool_output));
        }
        list.appendChild(item);
      });
      var total = document.createElement('li');
      total.className = 'hint';
      total.textContent = 'Completed in ' + (trace.total_duration_ms || 0) + ' ms';
      list.appendChild(total);
    })
    .catch(function (error) {
      list.innerHTML = '<li class="hint">Trace unavailable (' + error.message + ').</li>';
    });

  function renderBlock(label, value) {
    var pre = document.createElement('pre');
    pre.textContent = label + ': ' + JSON.stringify(value, null, 1);
    return pre;
  }
})();
