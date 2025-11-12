// Chart configurations
const chartConfig = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            position: 'bottom',
        }
    }
};

// Daily Sales Chart
const dailySalesCtx = document.getElementById('dailySalesChart').getContext('2d');
const dailySalesChart = new Chart(dailySalesCtx, {
    type: 'line',
    data: {
        labels: {{ daily_sales|safe|yesno:"[],[]"|default:"[]" }}.map(item => {
            const date = new Date(item.day);
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        }),
        datasets: [{
            label: 'Sales Count',
            data: {{ daily_sales|safe|yesno:"[],[]"|default:"[]" }}.map(item => item.count),
            borderColor: '#007bff',
            backgroundColor: 'rgba(0, 123, 255, 0.1)',
            tension: 0.4,
            fill: true
        }, {
            label: 'Revenue (UGX)',
            data: {{ daily_sales|safe|yesno:"[],[]"|default:"[]" }}.map(item => item.total),
            borderColor: '#28a745',
            backgroundColor: 'rgba(40, 167, 69, 0.1)',
            tension: 0.4,
            yAxisID: 'y1'
        }]
    },
    options: {
        ...chartConfig,
        scales: {
            y: {
                type: 'linear',
                display: true,
                position: 'left',
                title: {
                    display: true,
                    text: 'Sales Count'
                }
            },
            y1: {
                type: 'linear',
                display: true,
                position: 'right',
                title: {
                    display: true,
                    text: 'Revenue (UGX)'
                },
                grid: {
                    drawOnChartArea: false,
                }
            }
        }
    }
});

// Payment Methods Chart
const paymentMethodsCtx = document.getElementById('paymentMethodsChart').getContext('2d');
const paymentMethodsChart = new Chart(paymentMethodsCtx, {
    type: 'doughnut',
    data: {
        labels: {{ payment_methods|safe|yesno:"[],[]"|default:"[]" }}.map(item => item.payment_method),
        datasets: [{
            data: {{ payment_methods|safe|yesno:"[],[]"|default:"[]" }}.map(item => item.total),
            backgroundColor: [
                '#007bff',
                '#28a745',
                '#ffc107',
                '#dc3545',
                '#6c757d',
                '#17a2b8'
            ],
            borderWidth: 0
        }]
    },
    options: {
        ...chartConfig,
        cutout: '60%',
        plugins: {
            legend: {
                position: 'bottom'
            }
        }
    }
});

// Hourly Sales Chart
const hourlySalesCtx = document.getElementById('hourlySalesChart').getContext('2d');
const hourlySalesChart = new Chart(hourlySalesCtx, {
    type: 'bar',
    data: {
        labels: Array.from({length: 24}, (_, i) => `${i}:00`),
        datasets: [{
            label: 'Sales by Hour',
            data: Array.from({length: 24}, () => Math.floor(Math.random() * 50)),
            backgroundColor: 'rgba(54, 162, 235, 0.8)',
            borderColor: 'rgba(54, 162, 235, 1)',
            borderWidth: 1
        }]
    },
    options: {
        ...chartConfig,
        scales: {
            y: {
                beginAtZero: true,
                title: {
                    display: true,
                    text: 'Number of Sales'
                }
            },
            x: {
                title: {
                    display: true,
                    text: 'Hour of Day'
                }
            }
        }
    }
});

// Utility functions
function setDateRange(range) {
    const today = new Date();
    let startDate, endDate = today;

    switch(range) {
        case 'today':
            startDate = today;
            break;
        case 'week':
            startDate = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
            break;
        case 'month':
            startDate = new Date(today.getFullYear(), today.getMonth(), 1);
            break;
        case 'quarter':
            const quarter = Math.floor(today.getMonth() / 3);
            startDate = new Date(today.getFullYear(), quarter * 3, 1);
            break;
        case 'year':
            startDate = new Date(today.getFullYear(), 0, 1);
            break;
    }

    document.querySelector('input[name="date_from"]').value = startDate.toISOString().split('T')[0];
    document.querySelector('input[name="date_to"]').value = endDate.toISOString().split('T')[0];
}

function exportData(format) {
    const params = new URLSearchParams(window.location.search);
    params.append('export', format);
    window.location.href = `{% url 'sales:analytics' %}?${params.toString()}`;
}

function toggleTableView() {
    const table = document.getElementById('dailySalesTable');
    table.classList.toggle('table-sm');
}

function viewDayDetails(date) {
    document.getElementById('selectedDate').textContent = new Date(date).toLocaleDateString();

    // Simulate loading day details
    const content = `
        <div class="text-center">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-2">Loading sales details...</p>
        </div>
    `;

    document.getElementById('dayDetailsContent').innerHTML = content;
    new bootstrap.Modal(document.getElementById('dayDetailsModal')).show();

    // Simulate API call
    setTimeout(() => {
        document.getElementById('dayDetailsContent').innerHTML = `
            <div class="row">
                <div class="col-md-4">
                    <div class="card text-center">
                        <div class="card-body">
                            <h5>Total Sales</h5>
                            <h3 class="text-primary">42</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card text-center">
                        <div class="card-body">
                            <h5>Revenue</h5>
                            <h3 class="text-success">UGX 850,000</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card text-center">
                        <div class="card-body">
                            <h5>Avg Sale</h5>
                            <h3 class="text-info">UGX 20,238</h3>
                        </div>
                    </div>
                </div>
            </div>
            <div class="mt-4">
                <h6>Hourly Breakdown</h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr><th>Hour</th><th>Sales</th><th>Revenue</th></tr>
                        </thead>
                        <tbody>
                            <tr><td>09:00-10:00</td><td>5</td><td>UGX 125,000</td></tr>
                            <tr><td>10:00-11:00</td><td>8</td><td>UGX 180,000</td></tr>
                            <tr><td>11:00-12:00</td><td>12</td><td>UGX 245,000</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }, 1000);
}

// Auto-refresh data every 5 minutes
setInterval(() => {
    if (document.visibilityState === 'visible') {
        location.reload();
    }
}, 5 * 60 * 1000);
