// New order form: customer type-ahead (fetch), running total, submit as JSON (jQuery AJAX).
$(function () {
  var timer;
  $('#customer').on('input', function () {
    var q = this.value;
    clearTimeout(timer);
    timer = setTimeout(function () {
      fetch(API_BASE + '/api/customers?q=' + encodeURIComponent(q), { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (customers) {
          $('#customer-suggestions').html(customers.map(function (c) {
            return '<li data-id="' + c.id + '">' + c.name + ' (' + c.segment + ')</li>';
          }).join(''));
        });
    }, 250);
  });
  $('#customer-suggestions').on('click', 'li', function () {
    $('#customerId').val($(this).data('id'));
    $('#customer').val($(this).text());
    $('#customer-suggestions').empty();
  });

  function lines() {
    return $('#lines tbody tr').map(function () {
      return { sku: $(this).find('[name=sku]').val(),
               quantity: parseInt($(this).find('[name=quantity]').val(), 10),
               unitPrice: parseFloat($(this).find('[name=unitPrice]').val() || '0') };
    }).get();
  }
  function recalc() {
    var total = lines().reduce(function (sum, l) { return sum + l.quantity * l.unitPrice; }, 0);
    $('#total').text(total.toFixed(2));
    $('#approval-hint').prop('hidden', total <= 10000);
  }
  $('#lines').on('input', 'input', recalc);
  $('#add-line').on('click', function () {
    $('#lines tbody tr:first').clone().find('input').val('').end().appendTo('#lines tbody');
  });

  $('#order-form').on('submit', function (e) {
    e.preventDefault();
    $.ajax({
      url: API_BASE + '/api/orders',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ customerId: Number($('#customerId').val()), lines: lines(), notes: $('#notes').val() }),
      dataType: 'json'
    }).done(function (order) {
      window.location = 'orders/' + order.id;
    }).fail(function (xhr) {
      $('#message').text((xhr.responseJSON && xhr.responseJSON.error) || 'The order could not be placed.');
    });
  });
});
