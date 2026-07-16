"""Popola image_url per gli hotel Partivia con immagini trovate sul web."""

from app import create_app
from models import db, PartiviaQuote

# Mappa hotel_name → image URL (trovate da siti ufficiali, Wikipedia, ecc.)
HOTEL_IMAGES = {
    "Grand Hyatt Barcelona": (
        "https://mbhub-wp.s3.eu-west-2.amazonaws.com/wp-content/uploads/"
        "2024/04/11121859/Hotel-Exterior-Outdoor-Swimming-Pool.-copy.jpg"
    ),
    "Hotel SB Diagonal Zero": (
        "https://static-resources-elementor.mirai.com/wp-content/uploads/"
        "sites/1193/piscina-panoramica-sb-diagonal-zero-2.webp"
    ),
    "The Westin Valencia": (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
        "0/07/Lanera_valencia.jpg/800px-Lanera_valencia.jpg"
    ),
    "Eurostars Torre Sevilla": (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
        "9/97/Torre_Sevilla_abril_2015.jpg/500px-Torre_Sevilla_abril_2015.jpg"
    ),
    "Pestana CR7 Gran Vía": (
        "https://estaticos.esmadrid.com/cdn/farfuture/"
        "extRLMXgrJ7SAgVSdDzC1yfGxTpCy7oKrXXay3qaa3I/"
        "mtime:1622712394/sites/default/files/recursosturisticos/"
        "alojamientos/grand-via-madrid-hotel_0.jpg"
    ),
    "VP Plaza España Design 5*": (
        "https://www.plazaespana-hotel.com/app/uploads/sites/384/"
        "banner-cascada2.jpg"
    ),
}


def main():
    app = create_app()
    with app.app_context():
        quotes = PartiviaQuote.query.all()
        updated = 0
        for q in quotes:
            if q.image_url:
                continue  # già ha un'immagine
            # Cerca match esatto o parziale
            url = HOTEL_IMAGES.get(q.hotel_name)
            if not url:
                for key, val in HOTEL_IMAGES.items():
                    if key.lower() in q.hotel_name.lower():
                        url = val
                        break
            if url:
                q.image_url = url
                updated += 1
                print(f"  ✓ {q.hotel_name} → immagine trovata")
            else:
                print(f"  ✗ {q.hotel_name} → nessuna immagine (inserisci manualmente)")

        db.session.commit()
        print(f"\nAggiornati {updated} hotel su {len(quotes)}.")
        print("Per gli hotel mancanti, incolla l'URL nella tab Input (colonna Foto URL).")


if __name__ == '__main__':
    main()
