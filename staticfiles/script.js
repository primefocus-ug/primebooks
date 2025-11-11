        document.addEventListener('DOMContentLoaded', function() {
            // Check if client info is already set (for demo purposes)
            const clientInfoSet = localStorage.getItem('clientInfoSet');
            const adminInfoSet = localStorage.getItem('adminInfoSet');
            
            if (!clientInfoSet) {
                document.getElementById('client-info-screen').classList.remove('d-none');
            } else if (!adminInfoSet) {
                document.getElementById('admin-info-screen').classList.remove('d-none');
            } else {
                document.getElementById('login-screen').classList.remove('d-none');
            }
            

            document.getElementById('clientInfoForm').addEventListener('submit', function(e) {
                e.preventDefault();
                localStorage.setItem('clientInfoSet', 'true');
                document.getElementById('client-info-screen').classList.add('d-none');
                document.getElementById('admin-info-screen').classList.remove('d-none');
            });
            
            document.getElementById('adminInfoForm').addEventListener('submit', function(e) {
                e.preventDefault();
                localStorage.setItem('adminInfoSet', 'true');
                document.getElementById('admin-info-screen').classList.add('d-none');
                document.getElementById('login-screen').classList.remove('d-none');
            });
            
            document.getElementById('loginForm').addEventListener('submit', function(e) {
                e.preventDefault();
                document.getElementById('auth-screens').classList.add('d-none');
                document.getElementById('main-dashboard').classList.remove('d-none');
                initializeDashboard();
            });
            
            document.getElementById('registerForm').addEventListener('submit', function(e) {
                e.preventDefault();
                alert('Registration successful! Please login.');
                document.getElementById('register-screen').classList.add('d-none');
                document.getElementById('login-screen').classList.remove('d-none');
            });
            

            document.getElementById('showRegister').addEventListener('click', function(e) {
                e.preventDefault();
                document.getElementById('login-screen').classList.add('d-none');
                document.getElementById('register-screen').classList.remove('d-none');
            });
            
            document.getElementById('showLogin').addEventListener('click', function(e) {
                e.preventDefault();
                document.getElementById('register-screen').classList.add('d-none');
                document.getElementById('login-screen').classList.remove('d-none');
            });
            
            // Logout functionality
            document.getElementById('logout').addEventListener('click', function(e) {
                e.preventDefault();
                document.getElementById('main-dashboard').classList.add('d-none');
                document.getElementById('auth-screens').classList.remove('d-none');
                document.getElementById('login-screen').classList.remove('d-none');
            });
            
            document.getElementById('logoutTop').addEventListener('click', function(e) {
                e.preventDefault();
                document.getElementById('main-dashboard').classList.add('d-none');
                document.getElementById('auth-screens').classList.remove('d-none');
                document.getElementById('login-screen').classList.remove('d-none');
            });
            
            // Sidebar toggle for mobile
            document.getElementById('sidebarToggle').addEventListener('click', function() {
                document.querySelector('.sidebar').classList.toggle('d-none');
            });
            
            // Section navigation
            document.querySelectorAll('[data-section]').forEach(link => {
                link.addEventListener('click', function(e) {
                    e.preventDefault();
                    const section = this.getAttribute('data-section');
                    

                    document.querySelectorAll('.sidebar .nav-link').forEach(navLink => {
                        navLink.classList.remove('active');
                    });
                    this.classList.add('active');
                    
                    // Hide all sections
                    document.querySelectorAll('.container-fluid[id$="-content"]').forEach(section => {
                        section.classList.add('d-none');
                    });
                    
                    // Show selected section
                    document.getElementById(`${section}-content`).classList.remove('d-none');
                });
            });
            

            document.querySelectorAll('.time-frame-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    document.querySelectorAll('.time-frame-btn').forEach(b => {
                        b.classList.remove('active');
                    });
                    this.classList.add('active');
                    updateCharts(this.getAttribute('data-timeframe'));
                });
            });
            

            function initializeDashboard() {
                // Set company name if available
                const companyName = localStorage.getItem('companyName');
                if (companyName) {
                    document.getElementById('companyNameDisplay').textContent = companyName;
                }
                

                initializeCharts();
                

                
            }
            
            // Initialize charts
            function initializeCharts() {

                const salesCtx = document.getElementById('salesChart').getContext('2d');
                const salesChart = new Chart(salesCtx, {
                    type: 'line',
                    data: {
                        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'],
                        datasets: [{
                            label: 'Sales',
                            data: [1200, 1900, 1700, 2100, 2400, 2800, 3200],
                            backgroundColor: 'rgba(106, 17, 203, 0.1)',
                            borderColor: 'rgba(106, 17, 203, 1)',
                            borderWidth: 2,
                            tension: 0.4,
                            fill: true
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: {
                                display: false
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true
                            }
                        }
                    }
                });
                

                const revenueCtx = document.getElementById('revenueChart').getContext('2d');
                const revenueChart = new Chart(revenueCtx, {
                    type: 'doughnut',
                    data: {
                        labels: ['Electronics', 'Clothing', 'Food', 'Other'],
                        datasets: [{
                            data: [35, 25, 20, 20],
                            backgroundColor: [
                                'rgba(106, 17, 203, 0.8)',
                                'rgba(37, 117, 252, 0.8)',
                                'rgba(0, 176, 155, 0.8)',
                                'rgba(244, 107, 69, 0.8)'
                            ],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: {
                                position: 'bottom'
                            }
                        }
                    }
                });
                

                window.salesChart = salesChart;
                window.revenueChart = revenueChart;
            }
            

            function updateCharts(timeframe) {
                // This would be replaced with actual data fetching in a real app
                let salesData, revenueData;
                
                switch(timeframe) {
                    case 'daily':
                        salesData = [120, 190, 170, 210, 240, 280, 320];
                        revenueData = [15, 25, 30, 30];
                        break;
                    case 'weekly':
                        salesData = [1200, 1900, 1700, 2100, 2400, 2800, 3200];
                        revenueData = [35, 25, 20, 20];
                        break;
                    case 'monthly':
                        salesData = [5000, 6000, 5500, 7000, 6500, 8000, 9000];
                        revenueData = [40, 20, 25, 15];
                        break;
                    case 'yearly':
                        salesData = [15000, 18000, 22000, 25000, 28000, 32000, 35000];
                        revenueData = [45, 15, 25, 15];
                        break;
                }
                
                // Update sales chart
                window.salesChart.data.datasets[0].data = salesData;
                window.salesChart.update();
                
                // Update revenue chart
                window.revenueChart.data.datasets[0].data = revenueData;
                window.revenueChart.update();
            }
        });