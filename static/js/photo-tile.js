document.addEventListener('DOMContentLoaded', () => {
    const photos = document.querySelectorAll('.photo-wrapper img');
    if (photos.length === 0) return;

    let index = 0;

    setInterval(() => {
        photos[index].classList.remove('active');
        index = (index + 1) % photos.length;
        photos[index].classList.add('active');
    }, 3000);
});
