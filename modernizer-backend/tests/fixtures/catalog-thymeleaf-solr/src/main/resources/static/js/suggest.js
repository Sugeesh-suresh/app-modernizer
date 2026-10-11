$(function () {
  $('#q').on('keyup', function () {
    var prefix = $(this).val();
    if (prefix.length < 2) { return; }
    $.getJSON('/api/search/suggest', { prefix: prefix }, function (names) {
      var list = $('#suggestions').empty();
      names.forEach(function (n) { list.append('<li>' + n + '</li>'); });
    });
  });
});
