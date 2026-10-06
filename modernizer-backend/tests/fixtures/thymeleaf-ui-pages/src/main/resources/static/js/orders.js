$(function () {
  $('.cancel-btn').on('click', function () {
    var id = $(this).data('id');
    $.post('/api/orders/' + id + '/cancel', function (res) {
      alert(res.message);
      $(this).prop('disabled', true);
    });
  });
  $('#refreshStatus').on('click', function () {
    var id = $(this).data('id');
    fetch('/api/orders/' + id + '/status')
      .then(function (r) { return r.json(); })
      .then(function (s) { $('#status').text(s.status); });
  });
  $('#jumpBtn').on('click', function () {
    var id = $('#quickJump').val();
    window.location.href = '/orders/' + id;
  });
  $('#results').on('click', '.row-pin', function () {
    $(this).toggleClass('pinned');
  });
});

function confirmBulk() {
  if (!confirm('Delete the selected orders?')) {
    return false;
  }
  window.location.href = '/orders?deleted=true';
}
