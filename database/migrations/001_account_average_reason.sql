-- pix-v1.2: permite o novo motivo sem reavaliar nem apagar análises existentes.
-- Executar com psql -v ON_ERROR_STOP=1. Pode ser reaplicado.
BEGIN;

ALTER TABLE pix_analysis DROP CONSTRAINT pix_analysis_reason_code_check;
ALTER TABLE pix_analysis ADD CONSTRAINT pix_analysis_reason_code_check CHECK (reason_code IN (
    'NEW_ACCOUNT_LIMIT_EXCEEDED',
    'DAILY_LIMIT_EXCEEDED',
    'MULE_DESTINATION',
    'MULE_PAYER',
    'SUSPECTED_MULE_FORWARDING',
    'NEW_DEVICE_HIGH_AMOUNT',
    'HIGH_FREQUENCY',
    'AMOUNT_ABOVE_ACCOUNT_AVERAGE',
    'POLICY_PASSED'
));

COMMIT;
