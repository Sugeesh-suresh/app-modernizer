// Orders list: paging, status filter and approval, all against order-services' JSON API.
$(function () {
  function row(o) {
    var approve = o.status === 'NEW' ? '<button class="approve">Approve</button>' : '';
    return '<tr data-id="' + o.id + '"><td><a href="orders/' + o.id + '">' + o.orderNumber + '</a></td><td>' +
      o.customerName + '</td><td class="status">' + o.status + '</td><td>' + o.total + '</td><td>' +
      new Date(o.createdAt).toLocaleDateString() + '</td><td>' + approve + '</td></tr>';
  }

  $('#more').on('click', function () {
    var page = $(this).data('page');
    $.getJSON(API_BASE + '/api/orders', { status: $('#status').val(), page: page, size: 20 }, function (orders) {
      $('#orders tbody').append($.map(orders, row).join(''));
      $('#more').data('page', page + 1).toggle(orders.length === 20);
    });
  });

  $('#orders').on('click', '.approve', function () {
    var tr = $(this).closest('tr');
    $.post(API_BASE + '/api/orders/' + tr.data('id') + '/approve')
      .done(function (res) { tr.find('.status').text(res.status); tr.find('.approve').remove(); })
      .fail(function (xhr) { alert((xhr.responseJSON && xhr.responseJSON.error) || 'Approval failed'); });
  });

  $('#filter').on('submit', function (e) {
    e.preventDefault();
    window.location = '?status=' + encodeURIComponent($('#status').val());
  });
});
