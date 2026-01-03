document.addEventListener('DOMContentLoaded', function () {
    const images = document.querySelectorAll('.photo-wrapper img');
    if (images.length === 0) return;

    let currentIndex = 0;

    function nextImage() {
        images[currentIndex].classList.remove('active');
        currentIndex = (currentIndex + 1) % images.length;
        images[currentIndex].classList.add('active');
    }

    setInterval(nextImage, 4000);
});
