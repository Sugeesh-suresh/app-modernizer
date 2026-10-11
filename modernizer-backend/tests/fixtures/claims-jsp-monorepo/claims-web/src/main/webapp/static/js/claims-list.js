$(document).ready(function () {
  loadClaims();
  $('#searchBtn').click(function () {
    $.ajax({
      url: '/claims-api/api/claims/search',
      type: 'GET',
      data: { policy: $('#policySearch').val() },
      success: render
    });
  });
});

function loadClaims() {
  $.get('/claims-api/api/claims', { status: $('#statusFilter').val() }, render);
}

function render(rows) {
  var body = $('#claimsBody').empty();
  rows.forEach(function (c) {
    body.append('<tr><td><a href="/claims/' + c.id + '">' + c.id + '</a></td><td>' + c.policyNumber + '</td><td>'
      + c.amount + '</td><td>' + c.status + '</td></tr>');
  });
}
