var hot;
var allJobs = [];
var standardColumns = [{ data: 'jobId', title: 'Job ID' }, { data: 'jobName', title: 'Job Name' },
  { data: 'status', title: 'Status' }, { data: 'attribute', title: 'Attribute' },
  { data: 'attributeType', title: 'Attribute Type' }, { data: 'edit', title: 'Edit' }];
var descriptionColumns = [{ data: 'jobId', title: 'Job ID' }, { data: 'jobName', title: 'Job Name' },
  { data: 'status', title: 'Status' }, { data: 'attribute', title: 'Attribute' },
  { data: 'description', title: 'Description' }, { data: 'edit', title: 'Edit' }, { data: 'run', title: 'Run' }];
var devColumns = [{ data: 'jobId', title: 'Job ID' }, { data: 'jobName', title: 'Job Name' },
  { data: 'fileName', title: 'File Name' }, { data: 'fileMatch', title: 'File Match' },
  { data: 'status', title: 'Status' }, { data: 'attribute', title: 'Attribute' }];

$(function () {
  hot = new Handsontable(document.getElementById('jobGrid'), { data: [], columns: standardColumns, readOnly: true });
  $.getJSON('/api/jobs', function (jobs) {
    allJobs = jobs;
    hot.loadData(jobs);
    $('#loadStatus').text('All Data loaded');
  });
  $('#jobSearch').on('keyup', filterJobs);
  $('#exactSearch').on('change', filterJobs);
  $('#viewSelect').on('change', function () {
    var view = $(this).val();
    switch (view) {
      case 'Description':
        hot.updateSettings({ columns: descriptionColumns });
        break;
      case 'Dev':
        hot.updateSettings({ columns: devColumns });
        break;
      default:
        hot.updateSettings({ columns: standardColumns });
    }
  });
});

function filterJobs() {
  var text = $('#jobSearch').val().toLowerCase();
  var field = $('#searchField').val();
  var exact = $('#exactSearch').is(':checked');
  var rows = allJobs.filter(function (j) {
    var v = String(j[field] || '').toLowerCase();
    return exact ? v === text : v.indexOf(text) >= 0;
  });
  hot.loadData(rows);
}
