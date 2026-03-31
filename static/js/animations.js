// animations.js - Collection of smooth website animations
// Add to your HTML: <script src="static/js/animations.js"></script>

// Utility function for smooth scrolling
function smoothScroll(target, duration = 1000) {
    const targetElement = document.querySelector(target);
    const targetPosition = targetElement.offsetTop;
    const startPosition = window.pageYOffset;
    const distance = targetPosition - startPosition;
    let startTime = null;

    function animation(currentTime) {
        if (startTime === null) startTime = currentTime;
        const timeElapsed = currentTime - startTime;
        const run = ease(timeElapsed, startPosition, distance, duration);
        window.scrollTo(0, run);
        if (timeElapsed < duration) requestAnimationFrame(animation);
    }

    function ease(t, b, c, d) {
        t /= d / 2;
        if (t < 1) return c / 2 * t * t + b;
        t--;
        return -c / 2 * (t * (t - 2) - 1) + b;
    }

    requestAnimationFrame(animation);
}

// Fade in elements on scroll
function fadeInOnScroll() {
    const elements = document.querySelectorAll('.fade-in');
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    });

    elements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
}

// Slide in from left/right
function slideInOnScroll() {
    const leftElements = document.querySelectorAll('.slide-in-left');
    const rightElements = document.querySelectorAll('.slide-in-right');

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.transform = 'translateX(0)';
                entry.target.style.opacity = '1';
            }
        });
    });

    leftElements.forEach(el => {
        el.style.transform = 'translateX(-100px)';
        el.style.opacity = '0';
        el.style.transition = 'transform 0.8s ease, opacity 0.8s ease';
        observer.observe(el);
    });

    rightElements.forEach(el => {
        el.style.transform = 'translateX(100px)';
        el.style.opacity = '0';
        el.style.transition = 'transform 0.8s ease, opacity 0.8s ease';
        observer.observe(el);
    });

    rightElements.forEach(el => {
        el.style.transform = 'translateX(100px)';
        el.style.opacity = '0';
        el.style.transition = 'transform 0.8s ease, opacity 0.8s ease';
        observer.observe(el);
    });
}

// Bounce animation for buttons
function addBounceEffect() {
    const buttons = document.querySelectorAll('.btn-bounce');
    buttons.forEach(btn => {
        btn.addEventListener('click', function() {
            this.style.animation = 'bounce 0.6s ease';
            setTimeout(() => {
                this.style.animation = '';
            }, 600);
        });
    });
}

// Pulse effect for highlights
function pulseEffect() {
    const elements = document.querySelectorAll('.pulse');
    elements.forEach(el => {
        el.style.animation = 'pulse 2s infinite';
    });
}

// Typing effect for text
function typeWriter(element, text, speed = 50) {
    let i = 0;
    element.innerHTML = '';
    function type() {
        if (i < text.length) {
            element.innerHTML += text.charAt(i);
            i++;
            setTimeout(type, speed);
        }
    }
    type();
}

// Counter animation for numbers
function animateCounter(element, target, duration = 2000) {
    const start = 0;
    const increment = target / (duration / 16);
    let current = start;

    const timer = setInterval(() => {
        current += increment;
        if (current >= target) {
            current = target;
            clearInterval(timer);
        }
        element.textContent = Math.floor(current);
    }, 16);
}

// Initialize all animations
function initAnimations() {
    fadeInOnScroll();
    slideInOnScroll();
    addBounceEffect();
    pulseEffect();

    // Example usage (uncomment and customize):
    // smoothScroll('#section', 1000);
    // typeWriter(document.querySelector('.typing-text'), 'Welcome to Marketplace!');
    // animateCounter(document.querySelector('.counter'), 1000);
}

// CSS animations (add to your CSS file)
const animationCSS = `
@keyframes bounce {
    0%, 20%, 53%, 80%, 100% { transform: translate3d(0,0,0); }
    40%, 43% { transform: translate3d(0,-30px,0); }
    70% { transform: translate3d(0,-15px,0); }
    90% { transform: translate3d(0,-4px,0); }
}

@keyframes pulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.05); }
    100% { transform: scale(1); }
}
`;

// Auto-initialize on page load
document.addEventListener('DOMContentLoaded', initAnimations);