/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package vmsrest

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"

	vast_client "github.com/vast-data/go-vast-client"
	"go.uber.org/zap"
)

// BeforeRequestFnCallback logs the outgoing HTTP request.
// The reconcile ID is already embedded in the logger name column by LogFor.
func BeforeRequestFnCallback(_ context.Context, _ *http.Request, verb, url string, body io.Reader, logger *zap.Logger) error {
	log := logger.WithOptions(zap.WithCaller(false))
	log.Info(">>>",
		zap.String("method", verb),
		zap.String("url", url),
	)

	if body != nil {
		bodyBytes, err := io.ReadAll(body)
		if err != nil {
			log.Error("failed to read request body", zap.Error(err))
			return err
		}

		trimmed := bytes.TrimSpace(bodyBytes)
		if len(trimmed) > 0 && !bytes.Equal(trimmed, []byte("null")) {
			var compact bytes.Buffer
			if err := json.Compact(&compact, trimmed); err == nil {
				log.Info("request JSON body", zap.Any("body", json.RawMessage(compact.Bytes())))
			} else {
				log.Info("request body (raw)", zap.ByteString("body", trimmed))
			}
		}
	}

	return nil
}

// AfterRequestFnCallback logs the HTTP response.
// The reconcile ID is already embedded in the logger name column by LogFor.
func AfterRequestFnCallback(_ context.Context, response vast_client.Renderable, logger *zap.Logger) (vast_client.Renderable, error) {
	log := logger.WithOptions(zap.WithCaller(false))
	log.Info("<<<", zap.Any("payload", json.RawMessage(response.PrettyJson("  "))))
	return response, nil
}
