/* static/info/js/info.js */

/* Initialize Particles.js */
particlesJS("particles-js", {
    "particles": {
        "number": {
            "value": 200,
            "density": {
                "enable": true,
                "value_area": 800
            }
        },
        "color": {
            "value": "#f39c12"
        },
        "shape": {
            "type": "star",
            "stroke": {
                "width": 0,
                "color": "#000000"
            }
        },
        "opacity": {
            "value": 0.7,
            "random": true
        },
        "size": {
            "value": 4,
            "random": true
        },
        "line_linked": {
            "enable": true,
            "distance": 150,
            "color": "#f39c12",
            "opacity": 0.5,
            "width": 1
        },
        "move": {
            "enable": true,
            "speed": 6,
            "direction": "none",
            "random": false,
            "straight": false,
            "out_mode": "out"
        }
    },
    "interactivity": {
        "detect_on": "canvas",
        "events": {
            "onhover": {
                "enable": true,
                "mode": "grab"
            },
            "onclick": {
                "enable": true,
                "mode": "push"
            }
        },
        "modes": {
            "grab": {
                "distance": 200,
                "line_linked": {
                    "opacity": 1
                }
            },
            "push": {
                "particles_nb": 5
            }
        }
    },
    "retina_detect": true
});

/* Initialize AOS (Animate On Scroll) */
AOS.init({
    duration: 1000,
    once: true
});

/* --- TradingView Chart --- */
/* Мы больше не используем TradingView для отображения графика,
   поэтому функцию инициализации можно закомментировать или удалить. */
// function initTradingViewChart() {
//     new TradingView.widget({
//         "width": "100%",
//         "height": 400,
//         "symbol": "BINANCE:BTCUSDT",
//         "interval": "D",
//         "timezone": "Etc/UTC",
//         "theme": "dark",
//         "style": "1",
//         "locale": "en",
//         "toolbar_bg": "#f39c12",
//         "enable_publishing": false,
//         "allow_symbol_change": true,
//         "container_id": "tradingview_chart"
//     });
// }
// initTradingViewChart();

/* Initialize Three.js for 3D Elements */
function initThreeJS() {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
        75,
        window.innerWidth / 400,
        0.1,
        1000
    );
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, 400);
    document.getElementById('threejs-scene').appendChild(renderer.domElement);

    // Create Torus Knot
    const torusGeometry = new THREE.TorusKnotGeometry(10, 3, 100, 16);
    const torusMaterial = new THREE.MeshStandardMaterial({ color: 0xf39c12, wireframe: true });
    const torusKnot = new THREE.Mesh(torusGeometry, torusMaterial);
    scene.add(torusKnot);

    // Create Rotating Cube
    const cubeGeometry = new THREE.BoxGeometry();
    const cubeMaterial = new THREE.MeshStandardMaterial({ color: 0x2ecc71 });
    const cube = new THREE.Mesh(cubeGeometry, cubeMaterial);
    cube.position.x = 25;
    scene.add(cube);

    // Add Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0xffffff, 1);
    pointLight.position.set(50, 50, 50);
    scene.add(pointLight);

    camera.position.z = 30;

    // Animation Loop
    function animate() {
        requestAnimationFrame(animate);
        torusKnot.rotation.x += 0.01;
        torusKnot.rotation.y += 0.01;
        cube.rotation.x += 0.02;
        cube.rotation.y += 0.02;
        renderer.render(scene, camera);
    }
    animate();

    // Handle Window Resize
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / 400;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, 400);
    });
}
initThreeJS();

/* Initialize Lottie Animation */
var rocketAnimation = lottie.loadAnimation({
    container: document.getElementById('lottie-animation'),
    renderer: 'svg',
    loop: true,
    autoplay: true,
    path: '/static/info/animations/rocket.json'
});

/* GSAP Animations */
gsap.from(".logo-img", { duration: 2, y: -100, opacity: 0, ease: "bounce" });
gsap.from(".hero-content h1", { duration: 1.5, x: -300, opacity: 0, ease: "power2.out" });
gsap.from(".hero-content p", { duration: 1.5, x: 300, opacity: 0, ease: "power2.out", delay: 0.5 });
gsap.from(".interactive-btn", { duration: 1.5, scale: 0, opacity: 0, ease: "back.out(1.7)", delay: 1 });
gsap.from(".subscription-card", { duration: 1, y: 50, opacity: 0, stagger: 0.2, ease: "power2.out" });

/* Initialize Mini-Game */
const gameCanvas = document.getElementById('gameCanvas');
const ctxGame = gameCanvas.getContext('2d');

let gameInterval;
let gameRunning = false;

// Simple Space Shooter Game
const player = {
    x: gameCanvas.width / 2 - 20,
    y: gameCanvas.height - 60,
    width: 40,
    height: 40,
    speed: 5,
    dx: 0
};

const bullets = [];
const enemies = [];
const enemySpeed = 2;
const bulletSpeed = 7;
const enemySpawnInterval = 1000; // Spawn enemy every 1 second
let score = 0;

function drawPlayer() {
    ctxGame.fillStyle = '#f39c12';
    ctxGame.fillRect(player.x, player.y, player.width, player.height);
}

function drawBullets() {
    ctxGame.fillStyle = '#2ecc71';
    bullets.forEach(bullet => {
        ctxGame.fillRect(bullet.x, bullet.y, bullet.width, bullet.height);
    });
}

function drawEnemies() {
    ctxGame.fillStyle = '#e74c3c';
    enemies.forEach(enemy => {
        ctxGame.fillRect(enemy.x, enemy.y, enemy.width, enemy.height);
    });
}

function drawScore() {
    ctxGame.fillStyle = '#ffffff';
    ctxGame.font = '20px Press Start 2P';
    ctxGame.fillText(`Score: ${score}`, 10, 30);
}

function movePlayer() {
    player.x += player.dx;
    // Boundary Detection
    if (player.x < 0) {
        player.x = 0;
    }
    if (player.x + player.width > gameCanvas.width) {
        player.x = gameCanvas.width - player.width;
    }
}

function moveBullets() {
    bullets.forEach((bullet, index) => {
        bullet.y -= bulletSpeed;
        if (bullet.y + bullet.height < 0) {
            bullets.splice(index, 1);
        }
    });
}

function moveEnemies() {
    enemies.forEach((enemy, index) => {
        enemy.y += enemySpeed;
        if (enemy.y > gameCanvas.height) {
            enemies.splice(index, 1);
        }
    });
}

function detectCollision() {
    enemies.forEach((enemy, eIndex) => {
        bullets.forEach((bullet, bIndex) => {
            if (
                bullet.x < enemy.x + enemy.width &&
                bullet.x + bullet.width > enemy.x &&
                bullet.y < enemy.y + enemy.height &&
                bullet.y + bullet.height > enemy.y
            ) {
                // Remove both enemy and bullet
                enemies.splice(eIndex, 1);
                bullets.splice(bIndex, 1);
                score += 10;
            }
        });
    });
}

function spawnEnemies() {
    const enemyWidth = 40;
    const enemyHeight = 40;
    const enemyX = Math.random() * (gameCanvas.width - enemyWidth);
    const enemyY = -enemyHeight;
    enemies.push({ x: enemyX, y: enemyY, width: enemyWidth, height: enemyHeight });
}

function draw() {
    ctxGame.clearRect(0, 0, gameCanvas.width, gameCanvas.height);
    drawPlayer();
    drawBullets();
    drawEnemies();
    drawScore();
}

function update() {
    movePlayer();
    moveBullets();
    moveEnemies();
    detectCollision();
    draw();
}

function startGame() {
    if (gameRunning) return;
    gameRunning = true;
    score = 0;
    gameInterval = setInterval(update, 30);
    setInterval(spawnEnemies, enemySpawnInterval);
    Swal.fire({
        title: 'Game Started!',
        text: 'Use Arrow Keys or Swipe to Move and Tap to Shoot.',
        icon: 'info',
        timer: 2000,
        showConfirmButton: false
    });
}

function stopGame() {
    clearInterval(gameInterval);
    gameRunning = false;
    ctxGame.clearRect(0, 0, gameCanvas.width, gameCanvas.height);
    Swal.fire({
        title: 'Game Over!',
        text: `Your Score: ${score}`,
        icon: 'error',
        confirmButtonText: 'Play Again'
    }).then(() => {
        startGame();
    });
}

function shootBullet() {
    const bulletWidth = 5;
    const bulletHeight = 10;
    const bulletX = player.x + player.width / 2 - bulletWidth / 2;
    const bulletY = player.y;
    bullets.push({ x: bulletX, y: bulletY, width: bulletWidth, height: bulletHeight });
}

// Key Handlers (Desktop)
document.addEventListener('keydown', (e) => {
    if (e.code === 'ArrowRight') {
        player.dx = player.speed;
    } else if (e.code === 'ArrowLeft') {
        player.dx = -player.speed;
    } else if (e.code === 'ArrowUp') {
        e.preventDefault();
        shootBullet();
    }
});

document.addEventListener('keyup', (e) => {
    if (e.code === 'ArrowRight' || e.code === 'ArrowLeft') {
        player.dx = 0;
    }
});

// Touch Controls (Mobile)
let touchStartX = null;

gameCanvas.addEventListener('touchstart', (e) => {
    const touch = e.touches[0];
    touchStartX = touch.clientX;
    shootBullet();
}, false);

gameCanvas.addEventListener('touchmove', (e) => {
    if (!touchStartX) return;
    const touch = e.touches[0];
    const touchX = touch.clientX;
    const diffX = touchX - touchStartX;

    if (diffX > 50) {
        player.dx = player.speed;
    } else if (diffX < -50) {
        player.dx = -player.speed;
    }
}, false);

gameCanvas.addEventListener('touchend', () => {
    player.dx = 0;
    touchStartX = null;
}, false);

// Mobile Shoot Button Handler
document.getElementById('mobile-shoot').addEventListener('click', () => {
    shootBullet();
});

// Start Game Button
document.getElementById('start-game').addEventListener('click', () => {
    startGame();
});

/* Basic Subscription Button */
document.getElementById('basic-subscription').addEventListener('click', () => {
    Swal.fire({
        title: 'Basic Subscription',
        text: 'Access core features and real-time market insights.',
        icon: 'info',
        confirmButtonText: 'Go to Bot'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot";
        }
    });
});

/* Premium Subscription Button */
document.getElementById('premium-subscription').addEventListener('click', () => {
    Swal.fire({
        title: 'Premium Subscription',
        text: 'Unlock advanced analytics, premium rewards, and exclusive features.',
        icon: 'warning',
        confirmButtonText: 'Join Premium'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = "https://t.me/TrendShare_bot";
        }
    });
});

/* Initialize Background Music */
const backgroundMusic = new Audio('/static/info/audio/background-music.mp3');
backgroundMusic.loop = true;
backgroundMusic.volume = 0.5;

// Play music on user interaction
document.body.addEventListener('click', () => {
    if (backgroundMusic.paused) {
        backgroundMusic.play();
    }
}, { once: true });

// Toggle Music Button
const musicToggleBtn = document.createElement('button');
musicToggleBtn.className = 'nes-btn is-primary music-toggle';
musicToggleBtn.innerText = '🔊';
musicToggleBtn.style.position = 'fixed';
musicToggleBtn.style.bottom = '20px';
musicToggleBtn.style.right = '20px';
musicToggleBtn.style.zIndex = '3000';
musicToggleBtn.style.borderRadius = '50%';
musicToggleBtn.style.width = '50px';
musicToggleBtn.style.height = '50px';
musicToggleBtn.style.fontSize = '1.5em';
document.body.appendChild(musicToggleBtn);

musicToggleBtn.addEventListener('click', () => {
    if (backgroundMusic.paused) {
        backgroundMusic.play();
        musicToggleBtn.innerText = '🔊';
    } else {
        backgroundMusic.pause();
        musicToggleBtn.innerText = '🔇';
    }
});

/* Initialize Easter Egg */
let secretCode = '';
const secret = 'UJOTOKEN';

document.addEventListener('keydown', (e) => {
    secretCode += e.key.toUpperCase();
    if (secretCode.includes(secret)) {
        secretCode = '';
        Swal.fire({
            title: '🎉 Surprise!',
            text: 'You have unlocked the secret feature!',
            icon: 'success',
            showCancelButton: true,
            confirmButtonText: 'Redeem Reward',
            cancelButtonText: 'Close'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = "https://t.me/TrendShare_bot";
            }
        });
    }
    if (secretCode.length > secret.length) {
        secretCode = secretCode.slice(-secret.length);
    }
});

const buttons = document.querySelectorAll('.nes-btn');
buttons.forEach(button => {
    button.addEventListener('mouseenter', () => {
        gsap.to(button, { scale: 1.1, duration: 0.3, ease: "power2.out" });
    });
    button.addEventListener('mouseleave', () => {
        gsap.to(button, { scale: 1, duration: 0.3, ease: "power2.out" });
    });
});

/* -- Мобильное меню (гамбургер) -- */
const hamburger = document.querySelector('.hamburger');
const navLinks = document.querySelector('.nav-links');

hamburger.addEventListener('click', () => {
    navLinks.classList.toggle('open');
});
