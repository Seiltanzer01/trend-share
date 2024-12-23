/* static/info/js/info.js */

// Инициализация AOS
document.addEventListener('DOMContentLoaded', function() {
    AOS.init();
});

// Инициализация Swiper для галереи
var gallerySwiper = new Swiper('.gallery-swiper', {
    slidesPerView: 3,
    spaceBetween: 30,
    loop: true,
    autoplay: {
        delay: 5000,
        disableOnInteraction: false,
    },
    pagination: {
        el: '.gallery-swiper .swiper-pagination',
        clickable: true,
    },
    navigation: {
        nextEl: '.gallery-swiper .swiper-button-next',
        prevEl: '.gallery-swiper .swiper-button-prev',
    },
    breakpoints: {
        768: {
            slidesPerView: 1,
        },
        1024: {
            slidesPerView: 2,
        },
        1440: {
            slidesPerView: 3,
        },
    }
});

// Инициализация Swiper для отзывов
var testimonialsSwiper = new Swiper('.testimonials-swiper', {
    slidesPerView: 1,
    spaceBetween: 30,
    loop: true,
    autoplay: {
        delay: 7000,
        disableOnInteraction: false,
    },
    pagination: {
        el: '.testimonials-swiper .swiper-pagination',
        clickable: true,
    },
    navigation: {
        nextEl: '.testimonials-swiper .swiper-button-next',
        prevEl: '.testimonials-swiper .swiper-button-prev',
    },
});

// Инициализация слайдера галереи
var gallerySwiper = new Swiper('.gallery-swiper', {
    slidesPerView: 3,
    spaceBetween: 30,
    loop: true,
    autoplay: {
        delay: 5000,
        disableOnInteraction: false,
    },
    pagination: {
        el: '.gallery-swiper .swiper-pagination',
        clickable: true,
    },
    navigation: {
        nextEl: '.gallery-swiper .swiper-button-next',
        prevEl: '.gallery-swiper .swiper-button-prev',
    },
    breakpoints: {
        768: {
            slidesPerView: 1,
        },
        1024: {
            slidesPerView: 2,
        },
        1440: {
            slidesPerView: 3,
        },
    }
});

// Инициализация диаграммы Chart.js
var ctx = document.getElementById('trendChart').getContext('2d');
var trendChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл'],
        datasets: [{
            label: 'Рыночные Тренды',
            data: [120, 190, 30, 50, 200, 30, 400],
            backgroundColor: 'rgba(255, 152, 0, 0.2)',
            borderColor: '#ff9800',
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointBackgroundColor: '#ff9800',
            pointRadius: 5,
            pointHoverRadius: 7,
        }]
    },
    options: {
        responsive: true,
        plugins: {
            legend: {
                position: 'top',
                labels: {
                    color: '#333',
                    font: {
                        size: 14,
                        weight: 'bold'
                    }
                }
            },
            tooltip: {
                enabled: true,
                backgroundColor: '#ff9800',
                titleColor: '#fff',
                bodyColor: '#fff',
                borderColor: '#fff',
                borderWidth: 1,
            }
        },
        scales: {
            x: {
                ticks: {
                    color: '#333',
                    font: {
                        size: 14,
                        weight: 'bold'
                    }
                },
                grid: {
                    display: false,
                }
            },
            y: {
                ticks: {
                    color: '#333',
                    font: {
                        size: 14,
                        weight: 'bold'
                    }
                },
                grid: {
                    color: '#ddd',
                },
                beginAtZero: true
            }
        }
    }
});

// Инициализация анимированных счетчиков
function animateCounters() {
    const counters = document.querySelectorAll('.counter');
    counters.forEach(counter => {
        const updateCount = () => {
            const target = +counter.getAttribute('data-target');
            const count = +counter.innerText;
            const speed = 200; // Скорость анимации

            const inc = target / speed;

            if (count < target) {
                counter.innerText = Math.ceil(count + inc);
                setTimeout(updateCount, 10);
            } else {
                counter.innerText = target;
            }
        };
        updateCount();
    });
}

window.addEventListener('scroll', () => {
    const countersSection = document.querySelector('#counters');
    const position = countersSection.getBoundingClientRect();

    if(position.top < window.innerHeight && position.bottom >=0 && !countersSection.classList.contains('counters-animated')) {
        animateCounters();
        countersSection.classList.add('counters-animated');
    }
});

// Обработчик открытия видео модала
const openVideoBtn = document.querySelector('.open-video-btn');
const videoModal = document.getElementById('videoModal');
const videoIframe = document.getElementById('videoIframe');
const closeVideoBtn = document.querySelector('.close-video');

openVideoBtn.addEventListener('click', () => {
    videoModal.style.display = 'block';
    videoIframe.src = 'https://www.youtube.com/embed/VIDEO_ID?autoplay=1';
});

closeVideoBtn.addEventListener('click', () => {
    videoModal.style.display = 'none';
    videoIframe.src = '';
});

window.addEventListener('click', (e) => {
    if (e.target == videoModal) {
        videoModal.style.display = 'none';
        videoIframe.src = '';
    }
});
