document.addEventListener('DOMContentLoaded', function () {
    const photos = document.querySelectorAll('.photo-wrapper img');
    if (!photos.length) return;

    let currentIndex = 0;

    function showNextPhoto() {
        photos[currentIndex].classList.remove('active');
        currentIndex = (currentIndex + 1) % photos.length;
        photos[currentIndex].classList.add('active');
    }

    setInterval(showNextPhoto, 3000);
});
