// Header search box: type-ahead from the Solr suggester through /api/search/suggest.
$(function () {
  var timer;
  $('#q').on('input', function () {
    var q = $(this).val();
    clearTimeout(timer);
    if (q.length < 2) { $('#suggestions').empty(); return; }
    timer = setTimeout(function () {
      $.ajax({ url: '/api/search/suggest', data: { q: q }, dataType: 'json' })
        .done(function (terms) {
          $('#suggestions').html($.map(terms, function (t) { return '<li>' + $('<span>').text(t).html() + '</li>'; }).join(''));
        });
    }, 200);
  });
  $('#suggestions').on('click', 'li', function () {
    $('#q').val($(this).text()).closest('form').submit();
  });
});
