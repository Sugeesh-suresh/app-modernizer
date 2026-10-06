var $j = jQuery.noConflict();
var AttributeSearch = {};

AttributeSearch.search = function () {
  var q = $j('#attrQuery').val();
  $.getJSON('/api/attributes/search', { q: q, showValues: $j('#showValues').is(':checked') }, function (rows) {
    $j('#attributeGrid').html(render(rows));
  });
};

$j(document).ready(function () {
  $('#searchButton').click(AttributeSearch.search);
  $j('#clearSearchButton').on('click', function () {
    $j('#attrQuery').val('');
    $j('#attributeGrid').empty();
  });
  $j('#showValues').on('change', AttributeSearch.search);
});
