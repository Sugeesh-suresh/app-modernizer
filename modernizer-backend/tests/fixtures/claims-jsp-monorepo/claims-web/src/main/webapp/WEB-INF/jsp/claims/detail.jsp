<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<!DOCTYPE html>
<html>
<head>
  <title>Claim detail</title>
  <script src="/static/js/jquery-3.6.0.min.js"></script>
</head>
<body>
<%@ include file="../common/header.jsp" %>
<h1>Claim <span id="claimNo">${claimId}</span></h1>
<dl id="claimInfo"></dl>
<textarea id="noteText" maxlength="500"></textarea>
<button type="button" id="addNoteBtn">Add note</button>
<button type="button" id="approveBtn" class="btn-approve">Approve</button>
<button type="button" id="rejectBtn" class="btn-reject">Reject</button>
<a href="/claims">Back to claims</a>
<script>
  var claimId = '${claimId}';
  $(function () {
    $.getJSON('/claims-api/api/claims/' + claimId, function (claim) {
      $('#claimInfo').html('<dt>Policy</dt><dd>' + claim.policyNumber + '</dd><dt>Amount</dt><dd>' + claim.amount + '</dd>');
    });
  });
  $('#approveBtn').on('click', function () {
    $.ajax({ url: '/claims-api/api/claims/' + claimId + '/decision', type: 'PUT', contentType: 'application/json',
             data: JSON.stringify({ decision: 'APPROVED' }),
             success: function () { location.reload(); } });
  });
  $('#rejectBtn').on('click', function () {
    $.ajax({ url: '/claims-api/api/claims/' + claimId + '/decision', type: 'PUT', contentType: 'application/json',
             data: JSON.stringify({ decision: 'REJECTED' }) });
  });
  document.getElementById('addNoteBtn').addEventListener('click', function () {
    fetch('/claims-api/api/claims/' + claimId + '/notes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: document.getElementById('noteText').value })
    }).then(function () { alert('Note added'); });
  });
</script>
</body>
</html>
