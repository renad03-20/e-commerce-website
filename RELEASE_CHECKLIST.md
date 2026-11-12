# Release checkpoint — 11 November 2026

The checkout and commission flows have automated regression coverage. This checkpoint is not a live-launch approval.

## What this update fixes

- Successful verified payments consume only their captured cart rows. Later additions, replacements, and reduced quantities are preserved; extra copies remain after subtracting the purchased quantity. Replayed events and browser refreshes do not consume the cart again.
- If inventory runs out during payment, all stock decrements roll back, fulfillment is frozen, and the whole payment is refunded. Lost refund responses recover through the existing refund ledger and stable idempotency key. A refund failure remains visible and retryable. No normal purchase emails are queued for that order.
- Ordered artwork cannot be deleted, including through admin. Set stock to zero to stop selling it. This preserves order prices, history, fulfillment and queued notifications.
- Stripe response handling supports both the previously locked SDK and the new locked SDK, including pagination and refund recovery.
- Checkout return/cancel URLs identify their own order, so another checkout tab does not replace their destination. Authentication and ownership checks remain in place.
- A guest can browse the gallery, add artwork, sign in and keep a cart. Merging respects current stock. Checkout still requires login; cart removal requires POST and CSRF protection.
- Past artist deadlines, nonpositive artwork prices and commission quotes below USD 0.50 are rejected. Commission quotes and checkout totals also have an upper payment limit. The buyer's optional budget remains a separate, positive advisory amount.
- Contact submissions are validated and saved in Django admin under Pages → Support messages. Refreshing does not send them twice. No support email is sent automatically and no reply-time promise is made.
- Runtime dependencies are included in Pipfile/Pipfile.lock; Django stays within the existing 6.0 series. Initial migrations for accounts, cart and products are included, and migrations are no longer ignored by Git. Static files use Django's current STORAGES setting.
- Home/contact FAQs describe implemented flows. Empty footer About/Blog links are removed.

## One local acceptance pass

Use Stripe test mode, with Django, the listener and `process_purchase_emails --watch` running.

1. In a private window, browse Gallery, add an artwork, then sign in as a buyer. The artwork must remain in the cart. Proceed to checkout.
2. Open Stripe Checkout for quantity 1. In another website tab, add a different artwork to the cart. Complete the original test payment. Expect webhook 200, the correct paid order, stock decreased once, and only the later artwork left in the cart. Refresh the confirmation page twice; nothing should repeat.
3. As the artist, try deleting that purchased artwork. Expect an explanation and the order history to remain intact. A never-ordered artwork can still be deleted.
4. Submit Contact & Support, then open admin → Pages → Support messages. Confirm one saved message with the right content. Mark it resolved if desired.

Existing unpaid checkouts created before this update have no cart snapshot: their cart is intentionally left alone after payment. Remove those purchased lines manually. Existing paid orders are not backfilled into the email queue.

## Before accepting real money

- Choose the hosting provider, public domain, production database, and persistent storage for public images and private commission files. Private files must never be exposed as a public media directory. Repeat the access tests on the deployed host.
- Configure SMTP and verify delivery to real buyer/artist inboxes. Console email is only a local preview. Run the purchase email worker as a supervised service and review failed/interrupted jobs.
- Register a production Stripe webhook with its production signing secret and the events handled by the app: checkout.session.completed, checkout.session.async_payment_succeeded, refund.created, refund.updated and refund.failed. A development CLI signing secret is separate. Verify HTTPS and signed-event handling on the actual host.
- Decide how artists receive their money. The current checkout code charges the platform account; it does not implement Stripe Connect payouts or a payout schedule. Do not advertise automated payouts until that mechanism exists.
- Replace/review the business details and sample terms/privacy policies before publication. They still contain placeholder addresses/contact details. Confirm shipping coverage, the fixed USD 10 shipping amount, the fixed 8% tax, cancellation/returns terms, and the applicable currency for the business.
- Run the production static build and Django deployment checks with real host settings. Test production database transactions, backups/restores, worker restart and refund recovery. The automated suite here uses SQLite, not the eventual production database.

## Reproducible checks

```bash
pipenv sync
pipenv run python manage.py test orders artwork accounts cart pages products --settings=storefront.test_settings
pipenv run python manage.py makemigrations --check --dry-run
pipenv run python manage.py check
```

With the production environment configured:

```bash
pipenv run python manage.py collectstatic --noinput
pipenv run python manage.py check --deploy --fail-level WARNING
```

The isolated test settings use an in-memory test database, local-memory email and fake Stripe keys. Never use them to run the deployed site.
